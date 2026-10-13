from pathlib import Path

from gulf_srt.segment import Word
from gulf_srt.transcript import SpeechSegment, Transcript, load_transcript, read_hotwords, read_names, save_transcript


def test_transcript_round_trip(tmp_path):
    (tmp_path / "clip.wav").write_bytes(b"")
    transcript = Transcript(
        words=[Word(0.0, 0.4, "هلا", 0.91), Word(0.4, 0.9, "عبود", 0.42)],
        duration=3.0,
        segments=[SpeechSegment(0.0, 0.9, "هلا عبود", -0.4, 0.01, 1.1)],
        source=str(tmp_path / "clip.wav"),
        hotwords="عبود",
        speech=[[0.0, 0.9]],
    )
    (tmp_path / "out").mkdir()
    save_transcript(transcript, tmp_path / "out" / "clip.words.json")
    saved = (tmp_path / "out" / "clip.words.json").read_text(encoding="utf-8")
    assert '"source": "../clip.wav"' in saved  # relative to the JSON file, not to where it was run
    loaded = load_transcript(tmp_path / "out" / "clip.words.json")
    assert loaded.words == transcript.words and loaded.speech == transcript.speech
    assert Path(loaded.source).resolve() == (tmp_path / "clip.wav").resolve()


def test_hotwords_file_skips_comments_and_blank_lines(tmp_path):
    file = tmp_path / "cast.txt"
    file.write_text("# cast of episode 1\nعبود\n\n أبو حمد \n", encoding="utf-8")
    assert read_names(file) == ["عبود", "أبو حمد"]
    assert read_hotwords("الديرة نت", file) == ["عبود", "أبو حمد", "الديرة", "نت"]
    assert read_hotwords() == []
