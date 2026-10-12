"""transcribe() with a stand-in model, so the settings sent to Whisper are tested without a download."""

from types import SimpleNamespace

from gulf_srt.transcribe import transcribe


class FakeModel:
    def __init__(self):
        self.settings = None

    def transcribe(self, audio, **settings):
        self.settings = settings
        word = SimpleNamespace(start=0.0, end=0.4, word=" عبود", probability=0.42)
        blank = SimpleNamespace(start=0.4, end=0.5, word=" ", probability=0.1)
        segment = SimpleNamespace(start=0.0, end=0.5, text=" عبود", avg_logprob=-0.5,
                                  no_speech_prob=0.02, compression_ratio=1.0, words=[word, blank])
        return iter([segment]), SimpleNamespace(duration=2.0)


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


def test_no_hotwords_sends_none():
    model = FakeModel()
    transcribe(model, "clip.wav", hotwords="")
    assert model.settings["hotwords"] is None
