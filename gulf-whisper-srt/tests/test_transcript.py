from gulf_srt.segment import Word
from gulf_srt.transcript import SpeechSegment, Transcript, load_transcript, read_hotwords, read_names, save_transcript


def test_transcript_round_trip(tmp_path):
    transcript = Transcript(
        words=[Word(0.0, 0.4, "هلا", 0.91), Word(0.4, 0.9, "عبود", 0.42)],
        duration=3.0,
        segments=[SpeechSegment(0.0, 0.9, "هلا عبود", -0.4, 0.01, 1.1)],
        source="clip.wav",
        hotwords="عبود",
    )
    save_transcript(transcript, tmp_path / "clip.words.json")
    assert load_transcript(tmp_path / "clip.words.json") == transcript


def test_hotwords_file_skips_comments_and_blank_lines(tmp_path):
    file = tmp_path / "cast.txt"
    file.write_text("# cast of episode 1\nعبود\n\n أبو حمد \n", encoding="utf-8")
    assert read_names(file) == ["عبود", "أبو حمد"]
    assert read_hotwords("الديرة", file) == "عبود أبو حمد الديرة"
    assert read_hotwords() == ""
