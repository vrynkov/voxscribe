import numpy as np

from app import pipeline
from app.merge import merge, to_text

DG_RESPONSE = {
    "results": {"channels": [{"alternatives": [{
        "languages": ["ru", "en"],
        "words": [
            {"word": "привет", "punctuated_word": "Привет!", "start": 0.0, "end": 0.5, "speaker": 0},
            {"word": "как", "punctuated_word": "Как", "start": 0.6, "end": 0.8, "speaker": 0},
            {"word": "дела", "punctuated_word": "дела?", "start": 0.9, "end": 1.2, "speaker": 0},
            {"word": "fine", "punctuated_word": "Fine,", "start": 1.6, "end": 1.9, "speaker": 1},
            {"word": "thanks", "punctuated_word": "thanks.", "start": 2.0, "end": 2.3, "speaker": 1},
        ],
    }]}]}
}


class FakeResp:
    status_code = 200
    text = ""

    def json(self):
        return DG_RESPONSE


def test_deepgram_engine(monkeypatch):
    import httpx
    sent = {}

    def fake_post(url, params=None, headers=None, content=None, timeout=None):
        sent.update(params=params, headers=headers, size=len(content))
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    audio = np.zeros(16000 * 3, dtype=np.float32)

    out = pipeline.deepgram_transcribe(audio, None)
    assert sent["params"]["language"] == "multi" and sent["params"]["diarize"] == "true"
    assert sent["headers"]["Authorization"] == "Token test-key" and sent["size"] > 0
    assert out["language"] == "ru, en"

    text = to_text(merge(out["words"], out["turns"]))
    assert text == "00:00 [Speaker 1]: Привет! Как дела?\n00:01 [Speaker 2]: Fine, thanks."


def test_engine_choice(monkeypatch):
    monkeypatch.delenv("ENGINE", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    assert pipeline.engine() == "local"
    monkeypatch.setenv("DEEPGRAM_API_KEY", "x")
    assert pipeline.engine() == "deepgram"
    monkeypatch.setenv("ENGINE", "local")
    assert pipeline.engine() == "local"
