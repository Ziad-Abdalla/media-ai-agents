from gulf_srt.qc import check
from gulf_srt.review import _isolate_quotes, review_page
from gulf_srt.segment import Cue, Rules, Word

CUES = [Cue(20.0, 22.0, ["يا عبود"])]
ISSUES = check(CUES, Rules(), words=[Word(20, 21, "يا", 0.11), Word(21, 22, "عبود", 0.9)],
               duration=30, speech=[[1.0, 19.0]])


def test_media_is_linked_relative_to_the_page(tmp_path):
    page = review_page(CUES, ISSUES, tmp_path / "media" / "ep01.mp4", tmp_path / "out" / "ep01.review.html", "ep01")
    assert 'src="../media/ep01.mp4"' in page


def test_video_files_get_a_video_player_and_audio_files_an_audio_player(tmp_path):
    out = tmp_path / "ep.review.html"
    assert "<video id=\"media\"" in review_page(CUES, ISSUES, tmp_path / "ep.MOV", out, "ep")
    assert "<audio id=\"media\"" in review_page(CUES, ISSUES, tmp_path / "ep.wav", out, "ep")


def test_issue_list_is_arabic_right_to_left_with_the_missing_dialogue_first(tmp_path):
    page = review_page(CUES, ISSUES, tmp_path / "ep.wav", tmp_path / "ep.review.html", "ep")
    assert '<html lang="ar" dir="rtl">' in page
    missing, wrong = page.index("ربما فات حوار"), page.index("قد تكون الكلمات خاطئة")
    assert missing < wrong  # the 18 s of skipped speech is listed before the unsure word
    assert "مقاطع بلا ترجمة<br>20 ثانية" in page


def test_review_page_keeps_arabic_words_in_their_own_direction():
    assert _isolate_quotes("unsure of: «يا» 0.11") == "unsure of: «<bdi>يا</bdi>» 0.11"
