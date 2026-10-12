import pytest

from gulf_srt.qc import (
    MAYBE_MISSING, MAYBE_WRONG, QUIET_GAP, READABILITY, QcRules, check, decode_windows, headline, run, summary,
    to_markdown, words_by_cue,
)
from gulf_srt.segment import Cue, Rules, Word
from gulf_srt.transcript import SpeechSegment, Transcript

RULES = Rules()


def kinds(issues):
    return [(i.kind, i.cue) for i in issues]


def test_words_are_given_back_to_their_cue():
    words = [Word(0, 1, "هلا"), Word(1, 2, "والله"), Word(3, 4, "كيفك؟")]
    cues = [Cue(0, 2, ["هلا والله"]), Cue(3, 4, ["كيفك؟"])]
    assert [[w.text for w in ws] for ws in words_by_cue(cues, words)] == [["هلا", "والله"], ["كيفك؟"]]


def test_unsure_words_are_listed_with_their_score():
    words = [Word(0, 1, "هلا", 0.95), Word(1, 2.5, "الظافيري", 0.21)]
    cues = [Cue(0, 2.5, ["هلا الظافيري"])]
    issues = check(cues, RULES, words=words)
    assert kinds(issues) == [("unsure-words", 1)]
    assert issues[0].priority == MAYBE_WRONG
    assert "«الظافيري» 0.21" in issues[0].detail


def test_a_score_just_under_the_line_never_prints_as_the_line():
    issues = check([Cue(0, 2, ["أيوه"])], RULES, words=[Word(0, 2, "أيوه", 0.4996)])
    assert "«أيوه» 0.49" in issues[0].detail


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


def test_whisper_window_scores():
    cues = [Cue(0, 3, ["لا لا لا لا لا لا"])]
    segments = [SpeechSegment(0, 3, "لا لا لا لا لا لا", avg_logprob=-1.3, no_speech_prob=0.8, compression_ratio=3.1)]
    found = [k for k, _ in kinds(check(cues, RULES, segments=segments))]
    assert {"maybe-not-speech", "repetition", "unsure-segment"} <= set(found)


def test_segments_from_one_window_are_flagged_once():
    # faster-whisper splits one decoded window into segments that share the same scores.
    shared = dict(avg_logprob=-1.2, no_speech_prob=0.1, compression_ratio=1.5)
    segments = [SpeechSegment(0, 2, "", **shared), SpeechSegment(2, 4, "", **shared),
                SpeechSegment(4, 6, "", avg_logprob=-0.2, no_speech_prob=0.1, compression_ratio=1.5)]
    assert [(a, b) for a, b, _ in decode_windows(segments)] == [(0, 4), (4, 6)]
    cues = [Cue(0, 2, ["اول"]), Cue(2, 4, ["ثاني"]), Cue(4, 6, ["ثالث"])]
    flags = [i for i in check(cues, RULES, segments=segments) if i.kind == "unsure-segment"]
    assert len(flags) == 1 and flags[0].cue == 1 and "(cues 1-2)" in flags[0].detail


def test_speech_with_no_subtitle_goes_to_the_top():
    # The hotwords failure: Whisper skipped the first 20 s, but the VAD heard speech there.
    words = [Word(20, 21, "يا", 0.11), Word(21, 22, "عبود", 0.9)]
    cues = [Cue(20, 22, ["يا عبود"])]
    issues = check(cues, RULES, words=words, duration=30, speech=[[1.0, 19.0], [20.0, 22.0]])
    assert issues[0].priority == MAYBE_MISSING and issues[0].kind == "missed-speech"
    assert (issues[0].start, issues[0].end, issues[0].speech_seconds) == (0.0, 20, 18.0)
    assert issues[1].kind == "unsure-words"


def test_a_long_gap_with_no_speech_heard_is_a_quick_check_at_the_end():
    cues = [Cue(0, 2, ["هلا"]), Cue(20, 22, ["هلا"])]
    issues = check(cues, RULES, speech=[[0, 2], [5, 6], [20, 22]], duration=22)
    gap = [i for i in issues if i.cue is None]
    assert [(i.kind, i.priority) for i in gap] == [("quiet-gap", QUIET_GAP)]


def test_without_speech_data_gaps_are_judged_by_length():
    cues = [Cue(20.0, 22.0, ["اول سطر"]), Cue(23.0, 25.0, ["ثاني سطر"]), Cue(40.0, 42.0, ["ثالث سطر"])]
    issues = check(cues, RULES, duration=60.0)
    assert [(i.start, i.end) for i in issues if i.kind == "long-gap"] == [(0.0, 20.0), (25.0, 40.0), (42.0, 60.0)]
    assert all(i.priority == MAYBE_MISSING for i in issues)


def test_order_is_missing_then_wrong_then_readability():
    words = [Word(15, 15.3, "نعم", 0.2)]
    cues = [Cue(15, 15.3, ["نعم"])]
    priorities = [i.priority for i in check(cues, RULES, words=words, duration=30)]
    assert priorities == sorted(priorities) and priorities[0] == MAYBE_MISSING and READABILITY in priorities


def test_gaps_are_counted_in_the_headline():
    cues = [Cue(20, 22, ["يا عبود"])]
    issues = check(cues, RULES, duration=22, speech=[[0, 19]])
    s = summary(cues, issues)
    assert (s["gaps_to_check"], s["gap_seconds"]) == (1, 20.0)
    assert headline(s) == "1 subtitles, 0 flagged (0%), plus 1 stretch with no subtitle to listen to (20 s)."


def test_edited_subtitles_are_not_matched_to_old_words():
    with pytest.raises(ValueError):
        check([Cue(0, 2, ["نص بعد التعديل"])], RULES, words=[Word(0, 2, "نص")])


def test_run_says_when_the_word_check_was_switched_off():
    transcript = Transcript([Word(0, 2, "نص", 0.1)], 2.0, speech=[[0, 2]])
    issues, notes = run([Cue(0, 2, ["نص بعد التعديل"])], RULES, transcript)
    assert notes == ["edited"]
    assert "Word confidence is off" in to_markdown([Cue(0, 2, ["نص"])], issues, "ep01", notes)


def test_clean_file_and_summary():
    cues = [Cue(0, 2, ["هلا والله"])]
    assert check(cues, RULES, QcRules(), words=[Word(0, 1, "هلا", 0.9), Word(1, 2, "والله", 0.9)]) == []
    assert summary(cues, []) == {"cues": 1, "cues_flagged": 0, "share_flagged": 0.0, "gaps_to_check": 0,
                                 "gap_seconds": 0.0, "by_kind": {}}
    assert "Nothing to flag." in to_markdown(cues, [], "ep01")
