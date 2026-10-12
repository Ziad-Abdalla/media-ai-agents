"""End to end from a saved transcript: no model, no GPU."""

import json

from gulf_srt import qc
from gulf_srt.archive import load_entries, search
from gulf_srt.cli import default_output, main
from gulf_srt.segment import Cue, Word
from gulf_srt.srt import write_srt
from gulf_srt.transcript import SpeechSegment, Transcript, save_transcript

WORDS = [Word(0.0, 0.5, "يا", 0.9), Word(0.5, 1.0, "عبود", 0.9), Word(1.0, 2.0, "</script>", 0.3)]


def save(tmp_path, name, media=None, words=WORDS):
    transcript = Transcript(words, 30.0, [SpeechSegment(0, 2, "", -0.3, 0.0, 1.2)],
                            source=str(media) if media else "", speech=[[0.0, 2.0]])
    save_transcript(transcript, tmp_path / f"{name}.words.json")
    return tmp_path / f"{name}.words.json"


def test_from_json_writes_every_output(tmp_path, capsys):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"")  # the review page only links to it
    main(["--from-json", str(save(tmp_path, "clip", media))])

    for suffix in (".srt", ".vtt", ".transcript.txt", ".index.json", ".qc.md", ".qc.json", ".review.html"):
        assert (tmp_path / f"clip{suffix}").exists(), suffix
    report = json.loads((tmp_path / "clip.qc.json").read_text(encoding="utf-8"))
    assert report["summary"]["by_kind"] == {"unsure-words": 1, "quiet-gap": 1}
    assert search(load_entries(tmp_path / "clip.index.json"), "عبود")[0]["start"] == 0.0
    page = (tmp_path / "clip.review.html").read_text(encoding="utf-8")
    assert 'src="clip.wav"' in page
    assert page.count("</script>") == 1  # the subtitle text can't close the page's script
    assert "review page ->" in capsys.readouterr().out


def test_dots_in_episode_names_are_kept(tmp_path):
    assert default_output("Show.S01E03.words.json") == default_output("Show.S01E03.wav")
    assert str(default_output("Show.S01E03.words.json")) == "Show.S01E03.srt"
    main(["--from-json", str(save(tmp_path, "Show.E01"))])
    main(["--from-json", str(save(tmp_path, "Show.E02", words=WORDS[:2]))])
    assert (tmp_path / "Show.E01.srt").exists() and (tmp_path / "Show.E02.srt").exists()
    assert not (tmp_path / "Show.srt").exists()
    assert "</script>" in (tmp_path / "Show.E01.srt").read_text(encoding="utf-8")  # E02 didn't overwrite it


def test_review_page_follows_the_json_or_media_option_from_any_folder(tmp_path, monkeypatch, capsys):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "ep.wav").write_bytes(b"")
    words = save(tmp_path, "ep", tmp_path / "media" / "ep.wav")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # run from a different folder than the one it was made in
    main(["--from-json", str(words)])
    assert 'src="media/ep.wav"' in (tmp_path / "ep.review.html").read_text(encoding="utf-8")

    (tmp_path / "media" / "ep.wav").unlink()
    (tmp_path / "ep.review.html").unlink()
    main(["--from-json", str(words)])
    assert "no review page" in capsys.readouterr().out and not (tmp_path / "ep.review.html").exists()
    (tmp_path / "moved.wav").write_bytes(b"")
    main(["--from-json", str(words), "--media", str(tmp_path / "moved.wav")])
    assert 'src="moved.wav"' in (tmp_path / "ep.review.html").read_text(encoding="utf-8")


def test_replacements_fix_names_before_cutting(tmp_path):
    rules = tmp_path / "fixes.txt"
    rules.write_text("عبود => أبو حمد\n", encoding="utf-8")
    main(["--from-json", str(save(tmp_path, "clip", words=WORDS[:2])), "--replacements", str(rules)])
    assert "يا أبو حمد" in (tmp_path / "clip.srt").read_text(encoding="utf-8")
    assert "أبو حمد" in (tmp_path / "clip.transcript.txt").read_text(encoding="utf-8")


def test_qc_command_on_an_edited_srt_says_word_confidence_is_off(tmp_path, capsys):
    words = save(tmp_path, "ep")
    write_srt([Cue(0.0, 2.0, ["يا عبود، تعال"])], tmp_path / "ep.srt")  # the editor changed the line
    qc.main([str(tmp_path / "ep.srt"), "--words", str(words)])
    report = (tmp_path / "ep.qc.md").read_text(encoding="utf-8")
    assert "Word confidence is off" in report and "unsure-words" not in report
    assert "edited after it was made" in capsys.readouterr().err
