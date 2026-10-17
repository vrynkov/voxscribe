"""
FastAPI server.

Flow (why jobs?): transcribing a long file can take minutes, longer than a browser
request should wait. So the upload returns a job id right away, the work runs in the
background, and the React app asks "is it done yet?" every 1.5 s.
"""
from __future__ import annotations

import logging
import math
import os
import secrets
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:  # read backend/.env when running locally (on the cloud, secrets come from settings)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from . import pipeline
from .merge import merge, to_text, words_with_punctuation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
MAX_AUDIO_MINUTES = int(os.getenv("MAX_AUDIO_MINUTES", "60"))
JOB_TTL_SECONDS = 2 * 3600
ALLOWED = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}
UPLOAD_DIR = Path(tempfile.gettempdir()) / "voxscribe"
UPLOAD_DIR.mkdir(exist_ok=True)

# ---- protect the paid API key on a public server ----
# All three are read once at startup, from the server's own settings. Nothing a
# visitor sends can change them. Leave them empty (e.g. on your laptop) = no limits.
DAILY_MINUTES = int(os.getenv("DAILY_MINUTES", "0"))  # audio minutes per day for everyone together; 0 = no cap
ACCESS_CODE = os.getenv("ACCESS_CODE", "")            # visitors must type this to upload
OWNER_CODE = os.getenv("OWNER_CODE", "")              # you: skips the code check and the daily cap

@asynccontextmanager
async def lifespan(_app):
    # Load the speaker model in the background so the first user doesn't wait for it.
    def _load():
        try:
            pipeline.load_diarizer()
            log.info("Diarization model ready")
        except Exception as e:
            log.warning("Could not preload diarization model: %s", e)
    log.info("Engine: %s", pipeline.engine())
    log.info("Limits: daily cap %s, access code %s, owner code %s",
             f"{DAILY_MINUTES} min" if DAILY_MINUTES else "off",
             "on" if ACCESS_CODE else "off", "on" if OWNER_CODE else "off")
    if pipeline.engine() == "local":
        threading.Thread(target=_load, daemon=True).start()
    yield


app = FastAPI(title="VoxScribe API", lifespan=lifespan)
app.add_middleware(  # lets the Vite dev server (port 5173) call the API locally
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"], allow_headers=["*"],
)

jobs: dict[str, dict] = {}
lock = threading.Lock()
worker = ThreadPoolExecutor(max_workers=1)  # one job at a time: the free CPU is small
usage = {"day": "", "seconds": 0.0}  # audio processed today (UTC), counted on the server


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _same(given: str, expected: str) -> bool:
    # compare_digest takes the same time whether the first or the last letter is wrong,
    # so nobody can guess the code letter by letter by timing the answers.
    return bool(expected) and secrets.compare_digest(given.encode(), expected.encode())


def minutes_used_today() -> float:
    with lock:
        if usage["day"] != _today():  # new day: start counting from zero
            usage.update(day=_today(), seconds=0.0)
        return usage["seconds"] / 60


def reserve_minutes(duration: float):
    """Count this file against today's cap, or refuse it. Uses the duration ffmpeg measured, never a number from the browser."""
    with lock:
        if usage["day"] != _today():
            usage.update(day=_today(), seconds=0.0)
        if usage["seconds"] + duration > DAILY_MINUTES * 60:
            # Round the file up and the time left down, so the message never reads "2.5 min, but 2.5 left".
            need = math.ceil(duration / 6) / 10
            left = max(0.0, math.floor((DAILY_MINUTES * 60 - usage["seconds"]) / 6) / 10)
            raise ValueError(f"This file is {need:.1f} min, but only {left:.1f} of today's {DAILY_MINUTES} "
                             "demo minutes are left. Try a shorter file, or come back tomorrow.")
        usage["seconds"] += duration


def update(job_id: str, **fields):
    with lock:
        jobs[job_id].update(fields, updated=time.time())


def cleanup_old_jobs():
    now = time.time()
    with lock:
        for jid in [j for j, v in jobs.items() if now - v["updated"] > JOB_TTL_SECONDS]:
            jobs.pop(jid, None)


@contextmanager
def estimated_progress(job_id: str, expected_seconds: float, start: float, end: float, detail: str):
    """
    Move the progress bar smoothly while a slow step runs that can't report progress.

    It's fast at first and slows down near the end, like a download estimate:
    after the expected time it is at about 63% of the way, and it never reaches
    `end`, so it can't claim "done" before the work really is.
    """
    stop = threading.Event()

    def tick():
        t0 = time.time()
        while not stop.wait(0.5):
            frac = 1 - math.exp(-(time.time() - t0) / max(expected_seconds, 1))
            update(job_id, progress=start + (end - start) * frac, detail=detail)

    update(job_id, progress=start, detail=detail)
    thread = threading.Thread(target=tick, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


def run_job(job_id: str, path: Path, language: str | None, num_speakers: int | None, capped: bool = False):
    try:
        update(job_id, status="processing", stage="Preparing audio", progress=0.05)
        audio = pipeline.prepare_audio(path)
        duration = len(audio) / pipeline.SAMPLE_RATE
        if duration > MAX_AUDIO_MINUTES * 60:
            raise ValueError(f"Audio is {duration/60:.0f} min; the limit is {MAX_AUDIO_MINUTES} min.")
        if capped:  # counted before the paid call, so a failed job still counts (the API may have charged)
            reserve_minutes(duration)

        update(job_id, stage="Transcribing speech", progress=0.1, duration=duration)
        eng = pipeline.engine()
        log.info("Job %s: %.0f s of audio, engine=%s", job_id[:8], duration, eng)
        warning = None

        if eng == "deepgram":
            # Fast path: one cloud call returns words and speakers together.
            # Deepgram doesn't report progress, so we show an estimate instead.
            with estimated_progress(job_id, expected_seconds=8 + duration * 0.04,
                                    start=0.1, end=0.9, detail="words and speakers in one pass"):
                dg = pipeline.deepgram_transcribe(audio, language)
            update(job_id, stage="Identifying speakers", progress=0.92, detail=None)
            language_out, words, turns = dg["language"], dg["words"], dg["turns"]
        else:
            tr = pipeline.transcribe(audio, language,
                                     on_progress=lambda p: update(job_id, progress=0.1 + 0.35 * p))
            update(job_id, stage="Identifying speakers", progress=0.5, detail="loading the speaker model")
            try:
                turns = pipeline.diarize(
                    audio, num_speakers=num_speakers,
                    min_speakers=None if num_speakers else 1,
                    max_speakers=None if num_speakers else 8,
                    on_progress=lambda p, label: update(job_id, progress=0.5 + 0.44 * p, detail=label),
                )
            except Exception as e:  # still return a transcript if speaker detection fails
                log.exception("diarization failed")
                turns, warning = [], f"Speaker detection failed ({e}); showing a single speaker."
            language_out = tr["language"]
            words = words_with_punctuation(tr["segments"], tr["words"])

        update(job_id, stage="Building transcript", progress=0.95, detail=None)
        utterances = merge(words, turns)
        speakers = sorted({u["speaker"] for u in utterances}, key=lambda s: int(s.split()[-1]))

        update(job_id, status="done", stage="Done", progress=1.0, result={
            "language": language_out,
            "duration": duration,
            "speakers": speakers,
            "utterances": utterances,
            "text": to_text(utterances),
            "warning": warning,
        })
    except Exception as e:
        log.exception("job %s failed", job_id)
        update(job_id, status="error", error=str(e))
    finally:
        path.unlink(missing_ok=True)


@app.get("/api/health")
def health():
    return {"ok": True, "engine": pipeline.engine(),
            "deepgram_key": bool(os.getenv("DEEPGRAM_API_KEY")),
            "groq_key": bool(os.getenv("GROQ_API_KEY")), "hf_token": bool(os.getenv("HF_TOKEN")),
            # "required" / "optional" (only the owner code exists) / "none": tells the page whether to show the code box
            "access_code": "required" if ACCESS_CODE else "optional" if OWNER_CODE else "none",
            # the cap is public on purpose: knowing it doesn't help anyone get past it
            "daily_minutes": DAILY_MINUTES, "minutes_used_today": round(minutes_used_today(), 1)}


@app.post("/api/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form("auto"),          # "auto" | "en" | "ru"
    num_speakers: int | None = Form(None),  # leave empty to auto-detect
    code: str = Form(""),                   # access code or owner code, if the server uses them
):
    cleanup_old_jobs()
    is_owner = _same(code, OWNER_CODE)
    if ACCESS_CODE and not is_owner and not _same(code, ACCESS_CODE):
        raise HTTPException(401, "Wrong or missing access code.")
    capped = bool(DAILY_MINUTES) and not is_owner
    if capped and minutes_used_today() >= DAILY_MINUTES:  # say no before the upload is even saved
        raise HTTPException(429, "The daily demo limit is reached. Please come back tomorrow.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Please upload an MP3.")
    if language not in ("auto", "en", "ru"):
        raise HTTPException(400, "language must be auto, en or ru")
    if num_speakers is not None and not 1 <= num_speakers <= 10:
        raise HTTPException(400, "num_speakers must be between 1 and 10")

    job_id = uuid.uuid4().hex
    path = UPLOAD_DIR / f"{job_id}{ext}"
    size, limit = 0, MAX_UPLOAD_MB * 1024 * 1024
    with path.open("wb") as out:  # stream to disk in 1 MB pieces; stop if too big
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
            out.write(chunk)

    with lock:
        jobs[job_id] = {"id": job_id, "status": "queued", "stage": "Waiting in queue", "progress": 0.0,
                        "filename": file.filename, "updated": time.time()}
    worker.submit(run_job, job_id, path, None if language == "auto" else language, num_speakers, capped)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found (it may have expired).")
        return {k: v for k, v in job.items() if k != "updated"}


# ---- serve the built React app (production / Docker) ----
DIST = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        target = DIST / full_path
        return FileResponse(target if full_path and target.is_file() else DIST / "index.html")
