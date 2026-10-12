"""End to end from a saved transcript: no model, no GPU."""

import json

from gulf_srt.archive import load_entries, search
from gulf_srt.cli import main
from gulf_srt.segment import Word
from gulf_srt.transcript import SpeechSegment, Transcript, save_transcript


def test_from_json_writes_every_output(tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"")  # the review page only links to it
    words = [Word(0.0, 0.5, "يا", 0.9), Word(0.5, 1.0, "عبود", 0.9), Word(1.0, 2.0, "</script>", 0.3)]
    transcript = Transcript(words, 30.0, [SpeechSegment(0, 2, "", -0.3, 0.0, 1.2)], source=str(media))
    save_transcript(transcript, tmp_path / "clip.words.json")

    main(["--from-json", str(tmp_path / "clip.words.json")])

    for suffix in (".srt", ".vtt", ".transcript.txt", ".index.json", ".qc.md", ".qc.json", ".review.html"):
        assert (tmp_path / f"clip{suffix}").exists(), suffix
    qc = json.loads((tmp_path / "clip.qc.json").read_text(encoding="utf-8"))
    assert qc["summary"]["by_kind"] == {"unsure-words": 1, "long-silence": 1}
    assert search(load_entries(tmp_path / "clip.index.json"), "عبود")[0]["start"] == 0.0
    page = (tmp_path / "clip.review.html").read_text(encoding="utf-8")
    assert 'src="clip.wav"' in page
    assert page.count("</script>") == 1  # the subtitle text can't close the page's script


def test_review_page_keeps_arabic_words_in_their_own_direction():
    from gulf_srt.review import _isolate_quotes

    assert _isolate_quotes("unsure of: «يا» 0.11") == "unsure of: «<bdi>يا</bdi>» 0.11"
