"""transcribe() with a stand-in model, so the settings sent to Whisper are tested without a download."""

from types import SimpleNamespace

import pytest

from gulf_srt import transcribe as transcribe_module
from gulf_srt.transcribe import fit_hotwords, transcribe


class FakeTokenizer:
    """One token per letter, which is roughly how Whisper treats rare Arabic names."""

    def encode(self, text, add_special_tokens=False):
        return SimpleNamespace(ids=[ord(ch) for ch in text])


class FakeModel:
    max_length = 448  # Whisper's limit; faster-whisper keeps hotwords to 448 // 2 - 1 = 223 tokens
    hf_tokenizer = FakeTokenizer()

    def __init__(self):
        self.settings = None

    def transcribe(self, audio, **settings):
        self.settings = settings
        word = SimpleNamespace(start=0.0, end=0.4, word=" عبود", probability=0.42)
        blank = SimpleNamespace(start=0.4, end=0.5, word=" ", probability=0.1)
        segment = SimpleNamespace(start=0.0, end=0.5, text=" عبود", avg_logprob=-0.5,
                                  no_speech_prob=0.02, compression_ratio=1.0, words=[word, blank])
        return iter([segment]), SimpleNamespace(duration=2.0)


@pytest.fixture(autouse=True)
def no_real_vad(monkeypatch):
    monkeypatch.setattr(transcribe_module, "detect_speech", lambda audio: [[0.0, 0.5]])


def test_hotwords_and_safety_settings_reach_whisper():
    model = FakeModel()
    transcript = transcribe(model, "clip.wav", hotwords="عبود أبو حمد")
    assert model.settings["hotwords"] == "عبود أبو حمد"
    assert model.settings["language"] == "ar"
    assert model.settings["vad_filter"] is True
    assert model.settings["condition_on_previous_text"] is False
    assert [(w.text, w.probability) for w in transcript.words] == [("عبود", 0.42)]  # the blank word is dropped
    assert transcript.segments[0].avg_logprob == -0.5
    assert transcript.hotwords == "عبود أبو حمد" and transcript.source == "clip.wav"
    assert transcript.speech == [[0.0, 0.5]]


def test_no_hotwords_sends_none():
    model = FakeModel()
    transcribe(model, "clip.wav", hotwords="")
    assert model.settings["hotwords"] is None


def test_a_long_cast_list_is_cut_by_whole_names_and_the_cut_is_recorded(capsys):
    names = " ".join(f"اسم{n:03d}" for n in range(60))  # 60 names of 6 letters: far over 223 tokens
    kept, dropped = fit_hotwords(FakeModel(), names)
    assert len(" " + kept) <= 223 and kept.split() + dropped.split() == names.split()

    model = FakeModel()
    transcript = transcribe(model, "clip.wav", hotwords=names)
    assert model.settings["hotwords"] == kept
    assert transcript.hotwords_dropped == dropped
    assert "were not used" in capsys.readouterr().err
