"""
Turns an MP3 into a speaker-labelled transcript. Two engines:

  "deepgram" (default, fast): one cloud call does words AND speakers.
              24 minutes of audio -> about 30 seconds. Free $200 credit.
  "local"    (backup, slow):  Groq Whisper for words + pyannote on our own CPU
              for speakers. Free forever, but speaker detection can take
              about as long as the audio itself.

Common first step: ffmpeg turns any upload into clean 16 kHz mono audio.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("pipeline")

SAMPLE_RATE = 16_000
CHUNK_SECONDS = 10 * 60          # send audio to Groq in 10-minute pieces (stays far below 25 MB)
GROQ_MODEL = os.getenv("GROQ_MODEL", "whisper-large-v3")  # best accuracy for Russian
DIARIZATION_MODEL = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")


def engine() -> str:
    """ENGINE=deepgram|local. If not set: Deepgram when its key exists, else local."""
    choice = os.getenv("ENGINE", "").strip().lower()
    if choice in ("deepgram", "local"):
        return choice
    return "deepgram" if os.getenv("DEEPGRAM_API_KEY") else "local"


# ---------------------------------------------------------------- 1. audio
def _ffmpeg(*args: str) -> bytes:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args],
                          capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')[:300]}")
    return proc.stdout


def prepare_audio(path: Path) -> np.ndarray:
    """Decode the upload to a float32 numpy array (16 kHz, mono)."""
    raw = _ffmpeg("-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-")
    audio = np.frombuffer(raw, dtype=np.float32)
    if audio.size < SAMPLE_RATE:  # shorter than 1 second
        raise ValueError("Audio is empty or too short.")
    return audio


def _chunk_to_mp3(audio: np.ndarray) -> bytes:
    """Small mono mp3 (32 kbps is plenty for speech) — faster to upload."""
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
        f.write(audio.astype(np.float32).tobytes())
        raw_path = f.name
    try:
        return _ffmpeg("-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", raw_path,
                       "-b:a", "32k", "-f", "mp3", "-")
    finally:
        os.unlink(raw_path)


# ---------------------------------------------------------------- 2. words
_groq_client = None


def _groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys")
        _groq_client = Groq()
    return _groq_client


def _as_dict(obj):
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def transcribe(audio: np.ndarray, language: str | None, on_progress=None) -> dict:
    """
    Returns {"language", "words": [{start,end,text}], "segments": [{start,end,text}]}.
    Long audio is cut into chunks; each chunk's times are shifted by its offset.
    """
    step = CHUNK_SECONDS * SAMPLE_RATE
    chunks = [audio[i:i + step] for i in range(0, len(audio), step)]
    words, segments, detected = [], [], None

    for idx, chunk in enumerate(chunks):
        offset = idx * CHUNK_SECONDS
        resp = _groq().audio.transcriptions.create(
            file=(f"chunk{idx}.mp3", _chunk_to_mp3(chunk)),
            model=GROQ_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            language=language or None,
            temperature=0.0,
        )
        data = _as_dict(resp)
        detected = detected or data.get("language")
        for w in data.get("words") or []:
            w = _as_dict(w)
            words.append({"start": w["start"] + offset, "end": w["end"] + offset, "text": w["word"]})
        for s in data.get("segments") or []:
            s = _as_dict(s)
            segments.append({"start": s["start"] + offset, "end": s["end"] + offset, "text": s["text"]})
        log.info("Transcribed chunk %d of %d", idx + 1, len(chunks))
        if on_progress:
            on_progress((idx + 1) / len(chunks))

    # Fallback: if no word times came back, treat each segment as one big "word".
    if not words:
        words = [dict(s) for s in segments]
    return {"language": detected, "words": words, "segments": segments}


# ---------------------------------------------------------------- 3. speakers
_pipeline = None


def load_diarizer():
    """Load pyannote once (takes ~10-30 s) and keep it in memory."""
    global _pipeline
    if _pipeline is None:
        import torch
        from pyannote.audio import Pipeline

        token = os.getenv("HF_TOKEN")
        if not token:
            raise RuntimeError("HF_TOKEN is not set (free Hugging Face token, see README).")
        _pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=token)
        # Process audio pieces in bigger batches: noticeably faster on CPU.
        for attr in ("embedding_batch_size", "segmentation_batch_size"):
            try:
                setattr(_pipeline, attr, 32)
            except Exception:
                pass
        if torch.cuda.is_available():
            _pipeline.to(torch.device("cuda"))
    return _pipeline


# pyannote works in steps. "embeddings" (making a voice fingerprint for each
# short piece of audio) is by far the slowest, so it gets most of the bar.
_STEP_RANGES = {"segmentation": (0.0, 0.15), "speaker_counting": (0.15, 0.2),
                "embeddings": (0.2, 0.95), "discrete_diarization": (0.95, 1.0)}
_STEP_NAMES = {"segmentation": "finding speech", "speaker_counting": "counting speakers",
               "embeddings": "learning each voice", "discrete_diarization": "assigning speakers"}


def _make_hook(on_progress):
    """pyannote calls this function as it works; we turn that into 0..1 progress."""
    last = {"logged": -1}

    def hook(step_name, step_artifact=None, file=None, total=None, completed=None, **_):
        lo, hi = _STEP_RANGES.get(step_name, (0.0, 1.0))
        frac = (completed / total) if total and completed is not None else 1.0
        pct = lo + (hi - lo) * frac
        label = _STEP_NAMES.get(step_name, step_name)
        if on_progress:
            on_progress(pct, label)
        if int(pct * 10) != last["logged"]:  # log every 10% so the server window shows life
            last["logged"] = int(pct * 10)
            log.info("Speaker detection: %s (%d%%)", label, pct * 100)
    return hook


def diarize(audio: np.ndarray, num_speakers: int | None = None,
            min_speakers: int | None = None, max_speakers: int | None = None,
            on_progress=None) -> list[tuple[float, float, str]]:
    """Returns speaker turns: [(start, end, "SPEAKER_00"), ...]."""
    import torch

    pipe = load_diarizer()
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers:
            kwargs["min_speakers"] = min_speakers
        if max_speakers:
            kwargs["max_speakers"] = max_speakers

    # Pass the waveform directly -> no extra audio-decoding libraries needed.
    waveform = torch.from_numpy(audio.copy()).unsqueeze(0)
    started = time.time()
    output = pipe({"waveform": waveform, "sample_rate": SAMPLE_RATE},
                  hook=_make_hook(on_progress), **kwargs)
    log.info("Speaker detection finished in %.0f s for %.0f s of audio",
             time.time() - started, len(audio) / SAMPLE_RATE)

    # community-1 offers an "exclusive" view (one speaker at a time) — ideal for transcripts.
    annotation = getattr(output, "exclusive_speaker_diarization", None)
    if annotation is None:
        annotation = getattr(output, "speaker_diarization", None)
    if annotation is None:
        annotation = output
    return [(seg.start, seg.end, label) for seg, _, label in annotation.itertracks(yield_label=True)]


# ---------------------------------------------------------------- fast engine
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")


def deepgram_transcribe(audio: np.ndarray, language: str | None) -> dict:
    """
    One request: Deepgram returns every word with its time AND a speaker number.
    language=None means "detect": we use Deepgram's "multi" mode, which also
    handles people switching between English and Russian mid-conversation.

    Returns {"language", "words": [{start,end,text}], "turns": [(start,end,label)]}
    so the rest of the app can treat it exactly like the local engine.
    """
    import httpx

    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set. Get a free key at https://console.deepgram.com")

    params = {
        "model": DEEPGRAM_MODEL,
        "language": language or "multi",
        "diarize": "true",
        "punctuate": "true",
        "smart_format": "true",
    }
    started = time.time()
    resp = httpx.post(
        DEEPGRAM_URL, params=params,
        headers={"Authorization": f"Token {key}", "Content-Type": "audio/mpeg"},
        content=_chunk_to_mp3(audio), timeout=600,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Deepgram error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    log.info("Deepgram finished in %.0f s for %.0f s of audio", time.time() - started, len(audio) / SAMPLE_RATE)

    alt = data["results"]["channels"][0]["alternatives"][0]
    words, turns = [], []
    for w in alt.get("words", []):
        words.append({"start": w["start"], "end": w["end"], "text": w.get("punctuated_word") or w["word"]})
        turns.append((w["start"], w["end"], f"DG_{w.get('speaker', 0)}"))

    detected = language
    if not detected:
        langs = alt.get("languages") or []
        if not langs:
            langs = [data["results"]["channels"][0].get("detected_language")]
        detected = ", ".join(l for l in langs if l) or None
    return {"language": detected, "words": words, "turns": turns}
