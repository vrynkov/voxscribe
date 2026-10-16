"""
Merge "what was said" (Whisper words) with "who said it" (pyannote turns).

Simple idea:
  1. Every word has a start/end time.
  2. Every speaker turn has a start/end time and a label.
  3. Give each word to the speaker whose turn overlaps it the most.
  4. Glue neighbouring words from the same speaker into one line.
"""
from __future__ import annotations

PAUSE_SPLIT_SECONDS = 2.5   # start a new line after a long silence
MAX_LINE_SECONDS = 45.0     # keep lines readable even if one person talks a lot


def format_ts(seconds: float) -> str:
    """75.4 -> '01:15', 3725 -> '1:02:05'."""
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def words_with_punctuation(segments: list[dict], words: list[dict]) -> list[dict]:
    """
    Whisper's word list has no punctuation, but its segment text does.
    If a segment's text splits into the same number of tokens as its words,
    swap in the punctuated tokens. Otherwise keep the plain words.
    """
    if not segments:
        return words
    out: list[dict] = []
    wi = 0
    for seg in segments:
        seg_words = []
        while wi < len(words) and words[wi]["start"] < seg["end"] - 0.01:
            seg_words.append(dict(words[wi]))
            wi += 1
        tokens = seg.get("text", "").split()
        if tokens and len(tokens) == len(seg_words):
            for w, t in zip(seg_words, tokens):
                w["text"] = t
        out.extend(seg_words)
    out.extend(dict(w) for w in words[wi:])
    return out


def _speaker_for(word: dict, turns: list[tuple[float, float, str]]) -> str | None:
    best, best_overlap = None, 0.0
    for start, end, spk in turns:
        overlap = min(end, word["end"]) - max(start, word["start"])
        if overlap > best_overlap:
            best, best_overlap = spk, overlap
    if best is not None:
        return best
    # No overlap (word sits in a gap): pick the closest turn.
    mid = (word["start"] + word["end"]) / 2
    closest = min(turns, key=lambda t: min(abs(t[0] - mid), abs(t[1] - mid)), default=None)
    return closest[2] if closest else None


def _join(tokens: list[str]) -> str:
    text = " ".join(t.strip() for t in tokens if t.strip())
    for p in (",", ".", "!", "?", ":", ";"):
        text = text.replace(f" {p}", p)
    return text


def merge(words: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    """Return utterances: [{start, end, speaker, text}] with speakers named 'Speaker 1', 'Speaker 2'..."""
    if not words:
        return []

    names: dict[str, str] = {}  # raw pyannote label -> friendly name (in order of appearance)

    def friendly(raw: str | None) -> str:
        raw = raw or "unknown"
        if raw not in names:
            names[raw] = f"Speaker {len(names) + 1}"
        return names[raw]

    utterances: list[dict] = []
    cur = None
    for w in words:
        spk = friendly(_speaker_for(w, turns)) if turns else "Speaker 1"
        new_line = (
            cur is None
            or spk != cur["speaker"]
            or w["start"] - cur["end"] > PAUSE_SPLIT_SECONDS
            or w["end"] - cur["start"] > MAX_LINE_SECONDS
        )
        if new_line:
            cur = {"start": w["start"], "end": w["end"], "speaker": spk, "tokens": [w["text"]]}
            utterances.append(cur)
        else:
            cur["end"] = w["end"]
            cur["tokens"].append(w["text"])

    return [
        {"start": round(u["start"], 2), "end": round(u["end"], 2),
         "speaker": u["speaker"], "text": _join(u["tokens"])}
        for u in utterances
    ]


def to_text(utterances: list[dict]) -> str:
    """'12:23 [Speaker 1]: hello there' — one line per utterance."""
    return "\n".join(f"{format_ts(u['start'])} [{u['speaker']}]: {u['text']}" for u in utterances)
