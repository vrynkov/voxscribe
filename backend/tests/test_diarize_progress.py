import sys
import types

import numpy as np

from app import pipeline


class Seg:
    def __init__(self, s, e):
        self.start, self.end = s, e


class FakeAnnotation:
    def __bool__(self):  # real empty Annotations are "falsy"; make sure we don't skip them
        return False

    def itertracks(self, yield_label=True):
        yield Seg(0, 1), "A", "SPEAKER_00"
        yield Seg(1, 2), "B", "SPEAKER_01"


class FakeOutput:
    exclusive_speaker_diarization = FakeAnnotation()


def fake_pipe(audio, hook=None, **kwargs):
    hook("segmentation", None)
    for i in range(1, 5):
        hook("embeddings", None, total=4, completed=i)
    hook("discrete_diarization", None)
    return FakeOutput()


def test_diarize_reports_progress(monkeypatch):
    if "torch" not in sys.modules:  # stand-in so the test runs without installing PyTorch
        try:
            import torch  # noqa: F401
        except ImportError:
            fake = types.SimpleNamespace(from_numpy=lambda a: types.SimpleNamespace(unsqueeze=lambda d: a))
            monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setattr(pipeline, "load_diarizer", lambda: fake_pipe)
    seen = []
    turns = pipeline.diarize(np.zeros(16000, dtype=np.float32), on_progress=lambda p, label: seen.append((p, label)))
    assert turns == [(0, 1, "SPEAKER_00"), (1, 2, "SPEAKER_01")]
    assert seen[-1][0] == 1.0
    assert [p for p, _ in seen] == sorted(p for p, _ in seen)  # only moves forward
    assert ("learning each voice") in {label for _, label in seen}
