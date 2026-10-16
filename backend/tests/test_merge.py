from app.merge import format_ts, merge, to_text, words_with_punctuation


def w(s, e, t):
    return {"start": s, "end": e, "text": t}


def test_format_ts():
    assert format_ts(0) == "00:00"
    assert format_ts(743.9) == "12:23"
    assert format_ts(3725) == "1:02:05"


def test_two_speakers_get_numbered_in_order():
    words = [w(0, .5, "Hello"), w(.6, 1, "there."), w(1.5, 2, "Привет!"), w(2.1, 2.5, "Как"), w(2.6, 3, "дела?")]
    turns = [(0, 1.2, "SPEAKER_07"), (1.3, 3.2, "SPEAKER_02")]
    out = merge(words, turns)
    assert [u["speaker"] for u in out] == ["Speaker 1", "Speaker 2"]
    assert out[1]["text"] == "Привет! Как дела?"
    assert to_text(out).splitlines()[0] == "00:00 [Speaker 1]: Hello there."


def test_word_in_gap_goes_to_nearest_speaker():
    out = merge([w(5, 5.4, "hmm")], [(0, 1, "A"), (5.6, 8, "B")])
    assert out[0]["speaker"] == "Speaker 1" and out[0]["text"] == "hmm"


def test_long_pause_splits_line():
    out = merge([w(0, 1, "one"), w(10, 11, "two")], [(0, 12, "A")])
    assert len(out) == 2


def test_no_turns_means_single_speaker():
    out = merge([w(0, 1, "solo")], [])
    assert out[0]["speaker"] == "Speaker 1"


def test_punctuation_restored_from_segments():
    words = [w(0, .5, "hello"), w(.5, 1, "world"), w(1.2, 2, "ok")]
    segs = [{"start": 0, "end": 1.1, "text": " Hello, world!"}, {"start": 1.1, "end": 2, "text": "Okay then"}]
    out = words_with_punctuation(segs, words)
    assert [x["text"] for x in out] == ["Hello,", "world!", "ok"]  # 2nd segment token count differs -> kept
