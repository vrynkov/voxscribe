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


# ---- daily cap and access codes ----
def _fake_deepgram(tmp_path, monkeypatch):
    mp3 = tmp_path / "talk.mp3"  # 3 seconds of audio
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=3", str(mp3)], check=True)
    monkeypatch.setenv("ENGINE", "deepgram")
    monkeypatch.setattr(pipeline, "deepgram_transcribe", lambda audio, lang: {
        "language": "en", "words": [{"start": 0, "end": 1, "text": "Hi."}], "turns": [(0, 1, "DG_0")]})
    monkeypatch.setattr(main, "usage", {"day": main._today(), "seconds": 0.0})
    return mp3.read_bytes()


def _run(client, audio, code=""):
    r = client.post("/api/transcribe", files={"file": ("talk.mp3", audio, "audio/mpeg")}, data={"code": code})
    if r.status_code != 200:
        return r.status_code, None
    for _ in range(50):
        job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    return 200, job


def test_access_code(tmp_path, monkeypatch):
    audio = _fake_deepgram(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "ACCESS_CODE", "letmein")
    with TestClient(main.app) as client:
        assert client.get("/api/health").json()["access_code"] == "required"
        assert _run(client, audio)[0] == 401
        assert _run(client, audio, "wrong")[0] == 401
        status, job = _run(client, audio, "letmein")
    assert status == 200 and job["status"] == "done"


def test_daily_cap_counts_server_measured_minutes(tmp_path, monkeypatch):
    audio = _fake_deepgram(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DAILY_MINUTES", 1)
    with TestClient(main.app) as client:
        assert _run(client, audio)[1]["status"] == "done"
        assert abs(main.usage["seconds"] - 3) < 0.2           # ffmpeg's 3 s, not anything the browser said
        main.usage["seconds"] = 58                            # 2 s left, the file is 3 s
        _, job = _run(client, audio)
        assert job["status"] == "error" and "demo minutes are left" in job["error"]
        main.usage["seconds"] = 60                            # nothing left: refused before the upload is saved
        assert _run(client, audio)[0] == 429


def test_new_day_resets_the_cap(tmp_path, monkeypatch):
    audio = _fake_deepgram(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DAILY_MINUTES", 1)
    monkeypatch.setattr(main, "usage", {"day": "2000-01-01", "seconds": 60.0})
    with TestClient(main.app) as client:
        assert _run(client, audio)[1]["status"] == "done"


def test_owner_code_skips_code_and_cap(tmp_path, monkeypatch):
    audio = _fake_deepgram(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "ACCESS_CODE", "letmein")
    monkeypatch.setattr(main, "OWNER_CODE", "a-long-random-owner-code")
    monkeypatch.setattr(main, "DAILY_MINUTES", 1)
    main.usage["seconds"] = 60
    with TestClient(main.app) as client:
        assert _run(client, audio, "letmein")[0] == 429
        status, job = _run(client, audio, "a-long-random-owner-code")
    assert status == 200 and job["status"] == "done"
    assert main.usage["seconds"] == 60                        # your own use isn't counted


def test_no_settings_means_no_limits(tmp_path, monkeypatch):
    audio = _fake_deepgram(tmp_path, monkeypatch)
    main.usage["seconds"] = 10 ** 6
    with TestClient(main.app) as client:
        assert client.get("/api/health").json()["access_code"] == "none"
        assert _run(client, audio)[1]["status"] == "done"


def test_cap_message_never_contradicts_itself(monkeypatch):
    # 150.4 s twice is 300.8 s: just over a 5-minute cap. Plain rounding would say "2.5 min, but 2.5 left".
    monkeypatch.setattr(main, "DAILY_MINUTES", 5)
    monkeypatch.setattr(main, "usage", {"day": main._today(), "seconds": 150.4})
    try:
        main.reserve_minutes(150.4)
        assert False, "should be refused"
    except ValueError as e:
        assert "This file is 2.6 min, but only 2.4 of today's 5" in str(e), e
