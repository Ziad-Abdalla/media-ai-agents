import pytest

from gulf_srt.qc import LOOK_FIRST, MISSING, READABILITY, QcRules, check, summary, to_markdown, words_by_cue
from gulf_srt.segment import Cue, Rules, Word
from gulf_srt.transcript import SpeechSegment

RULES = Rules()


def kinds(issues):
    return [(i.kind, i.cue) for i in issues]


def test_words_are_given_back_to_their_cue():
    words = [Word(0, 1, "هلا"), Word(1, 2, "والله"), Word(3, 4, "كيفك؟")]
    cues = [Cue(0, 2, ["هلا والله"]), Cue(3, 4, ["كيفك؟"])]
    assert [[w.text for w in ws] for ws in words_by_cue(cues, words)] == [["هلا", "والله"], ["كيفك؟"]]


def test_unsure_words_are_listed_first():
    words = [Word(0, 1, "هلا", 0.95), Word(1, 2.5, "الظافيري", 0.21)]
    cues = [Cue(0, 2.5, ["هلا الظافيري"])]
    issues = check(cues, RULES, words=words)
    assert kinds(issues) == [("unsure-words", 1)]
    assert issues[0].priority == LOOK_FIRST
    assert "«الظافيري» 0.21" in issues[0].detail


def test_readability_problems():
    cues = [
        Cue(0.0, 0.5, ["نعم"]),  # too short
        Cue(1.0, 2.0, ["طيب يا ابو محمد خلنا نبدا الشغل الحين"]),  # 37 characters in 1 s: too fast
        Cue(3.0, 10.0, ["ا" * 50, "ب", "ج"]),  # on screen 7 s, a 50-character line, three lines
    ]
    found = kinds(check(cues, RULES))
    assert ("too-short", 1) in found
    assert ("too-fast", 2) in found
    assert {("too-long", 3), ("line-too-long", 3), ("too-many-lines", 3)} <= set(found)


def test_whisper_segment_scores():
    cues = [Cue(0, 3, ["لا لا لا لا لا لا"])]
    segments = [SpeechSegment(0, 3, "لا لا لا لا لا لا", avg_logprob=-1.3, no_speech_prob=0.8, compression_ratio=3.1)]
    found = [k for k, _ in kinds(check(cues, RULES, segments=segments))]
    assert {"maybe-not-speech", "repetition", "unsure-segment"} <= set(found)


def test_long_silences_at_start_middle_and_end():
    cues = [Cue(20.0, 22.0, ["اول سطر"]), Cue(23.0, 25.0, ["ثاني سطر"]), Cue(40.0, 42.0, ["ثالث سطر"])]
    gaps = [(i.start, i.end) for i in check(cues, RULES, duration=60.0) if i.kind == "long-silence"]
    assert gaps == [(0.0, 20.0), (25.0, 40.0), (42.0, 60.0)]
    assert all(i.priority == MISSING for i in check(cues, RULES, duration=60.0))


def test_order_is_words_then_readability_then_gaps():
    words = [Word(15, 15.3, "نعم", 0.2)]
    cues = [Cue(15, 15.3, ["نعم"])]
    priorities = [i.priority for i in check(cues, RULES, words=words, duration=30)]
    assert priorities == sorted(priorities) and priorities[0] == LOOK_FIRST and READABILITY in priorities


def test_edited_subtitles_are_not_matched_to_old_words():
    with pytest.raises(ValueError):
        check([Cue(0, 2, ["نص بعد التعديل"])], RULES, words=[Word(0, 2, "نص")])


def test_clean_file_and_summary():
    cues = [Cue(0, 2, ["هلا والله"])]
    assert check(cues, RULES, QcRules(), words=[Word(0, 1, "هلا", 0.9), Word(1, 2, "والله", 0.9)]) == []
    assert summary(cues, []) == {"cues": 1, "cues_flagged": 0, "share_flagged": 0.0, "by_kind": {}}
    assert "Nothing to flag." in to_markdown(cues, [], "ep01", has_confidence=True)
