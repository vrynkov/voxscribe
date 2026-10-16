import subprocess
import time

from fastapi.testclient import TestClient

from app import main, pipeline


def test_upload_to_transcript(tmp_path, monkeypatch):
    mp3 = tmp_path / "talk.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=3", str(mp3)], check=True)

    monkeypatch.setenv("ENGINE", "local")
    monkeypatch.setattr(pipeline, "load_diarizer", lambda: None)
    monkeypatch.setattr(pipeline, "transcribe", lambda audio, lang, on_progress=None: {
        "language": "russian",
        "words": [{"start": 0, "end": 1, "text": "привет"}, {"start": 1.5, "end": 2.5, "text": "hello"}],
        "segments": [{"start": 0, "end": 1.2, "text": "Привет."}, {"start": 1.2, "end": 3, "text": "Hello!"}],
    })
    monkeypatch.setattr(pipeline, "diarize", lambda audio, **kw: [(0, 1.2, "S0"), (1.3, 3, "S1")])

    with TestClient(main.app) as client:
        r = client.post("/api/transcribe", files={"file": ("talk.mp3", mp3.read_bytes(), "audio/mpeg")},
                        data={"language": "auto"})
        job_id = r.json()["job_id"]
        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.1)
    assert job["status"] == "done", job
    assert job["result"]["text"] == "00:00 [Speaker 1]: Привет.\n00:01 [Speaker 2]: Hello!"


def test_rejects_wrong_type():
    with TestClient(main.app) as client:
        r = client.post("/api/transcribe", files={"file": ("x.exe", b"1")})
    assert r.status_code == 400


def test_upload_with_deepgram_engine(tmp_path, monkeypatch):
    mp3 = tmp_path / "talk.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=3", str(mp3)], check=True)
    monkeypatch.setenv("ENGINE", "deepgram")
    monkeypatch.setattr(pipeline, "deepgram_transcribe", lambda audio, lang: {
        "language": "ru",
        "words": [{"start": 0, "end": 1, "text": "Привет."}, {"start": 1.5, "end": 2, "text": "Hi!"}],
        "turns": [(0, 1, "DG_0"), (1.5, 2, "DG_1")],
    })
    with TestClient(main.app) as client:
        job_id = client.post("/api/transcribe", files={"file": ("talk.mp3", mp3.read_bytes(), "audio/mpeg")}).json()["job_id"]
        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert client.get("/api/health").json()["engine"] == "deepgram"
    assert job["status"] == "done", job
    assert job["result"]["speakers"] == ["Speaker 1", "Speaker 2"]


def test_estimated_progress_moves_and_stays_below_end():
    main.jobs["t"] = {"id": "t", "status": "processing", "progress": 0.0, "updated": time.time()}
    seen = []
    with main.estimated_progress("t", expected_seconds=1, start=0.1, end=0.9, detail="x"):
        for _ in range(5):
            time.sleep(0.5)
            seen.append(main.jobs["t"]["progress"])
    assert seen == sorted(seen) and seen[-1] > 0.5   # keeps moving forward
    assert seen[-1] < 0.9                            # never claims "done"
    main.jobs.pop("t")
