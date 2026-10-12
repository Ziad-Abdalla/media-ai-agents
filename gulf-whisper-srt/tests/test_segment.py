from gulf_srt.segment import Cue, Rules, Word, build_cues, wrap_lines

RULES = Rules()


def words_from(text: str, start: float = 0.0, step: float = 0.4) -> list[Word]:
    """Fake Whisper output: one word every `step` seconds, no gaps."""
    words = []
    for i, token in enumerate(text.split()):
        words.append(Word(start + i * step, start + (i + 1) * step, token))
    return words


LONG_TEXT = (
    "والله يا عبود لو انك ساكن في الخرج كان قلت ماشي لكن انت ساكن جنب الوزارة "
    "وتقول اقوم من الفجر علشان الرياضة وانا اشوفك كل يوم تجي متاخر على الدوام"
)


def test_short_text_is_one_line():
    assert wrap_lines("مرحبا بكم", 42) == ["مرحبا بكم"]


def test_wrap_balances_two_lines():
    lines = wrap_lines("كلمة " * 12, 42)
    assert len(lines) == 2
    assert all(len(line) <= 42 for line in lines)
    assert abs(len(lines[0]) - len(lines[1])) <= 5


def test_wrap_returns_none_when_text_needs_three_lines():
    assert wrap_lines("كلمة " * 30, 42) is None


def test_lines_never_exceed_limits():
    for cue in build_cues(words_from(LONG_TEXT), RULES):
        assert 1 <= len(cue.lines) <= 2
        assert all(len(line) <= RULES.max_line_chars for line in cue.lines)


def test_no_words_are_lost():
    cues = build_cues(words_from(LONG_TEXT), RULES)
    assert " ".join(c.text for c in cues) == LONG_TEXT


def test_durations_within_limits_and_no_overlaps():
    cues = build_cues(words_from(LONG_TEXT, step=0.5), RULES)
    for cue in cues:
        assert cue.end - cue.start <= RULES.max_duration + 1e-9
        assert cue.end - cue.start >= RULES.min_duration - 1e-9
    for first, second in zip(cues, cues[1:]):
        assert first.end <= second.start


def test_sentence_end_starts_new_cue():
    cues = build_cues(words_from("صباح الخير يا جماعة. كيف حالكم اليوم؟"), RULES)
    assert [c.text for c in cues] == ["صباح الخير يا جماعة.", "كيف حالكم اليوم؟"]


def test_long_pause_starts_new_cue():
    words = words_from("انا جاي الحين") + words_from("وين المفتاح يا فيصل", start=5.0)
    cues = build_cues(words, RULES)
    assert [c.text for c in cues] == ["انا جاي الحين", "وين المفتاح يا فيصل"]


def test_short_cue_is_stretched_to_min_duration_and_reading_speed():
    words = [Word(0.0, 0.3, "هلا"), Word(10.0, 10.5, "طيب يا ابو محمد خلنا نبدا الشغل")]
    cues = build_cues(words, RULES)
    assert cues[0].end - cues[0].start >= RULES.min_duration
    second = cues[1]
    assert len(second.text) / (second.end - second.start) <= RULES.max_cps + 1e-9


def test_stretching_never_overlaps_next_cue():
    words = [Word(0.0, 0.2, "اي."), Word(0.5, 2.0, "خلاص فهمت عليك يا ابن الحلال")]
    cues = build_cues(words, RULES)
    for first, second in zip(cues, cues[1:]):
        assert first.end <= second.start


def test_tiny_cue_is_merged_into_neighbour():
    # "ايه." ends a sentence, so it would be its own one-word cue; it gets merged.
    words = [Word(0.0, 0.4, "ايه."), Word(0.6, 1.2, "تمام"), Word(1.2, 2.0, "خلنا نمشي")]
    cues = build_cues(words, RULES)
    assert len(cues) == 1
    assert cues[0].text == "ايه. تمام خلنا نمشي"


def test_tiny_cue_not_merged_across_long_gap():
    words = [Word(0.0, 0.4, "ايه."), Word(3.0, 4.5, "طيب وين رحت امس")]
    cues = build_cues(words, RULES)
    assert len(cues) == 2


def test_overlapping_whisper_times_are_clamped():
    cues = [Cue(0.0, 3.0, ["a"]), Cue(2.0, 4.0, ["b"])]
    from gulf_srt.segment import _fix_timing

    _fix_timing(cues, RULES)
    assert cues[0].end <= cues[1].start


def test_wrap_prefers_break_after_punctuation():
    lines = wrap_lines("يا ابن الحلال، انا اقوم بدري علشان الرياضة انت تعرفني", 42)
    assert lines[0] == "يا ابن الحلال،"


def test_forced_cut_moves_back_to_punctuation():
    # 16 words at 0.4 s each = 6.4 s, so the 6 s limit forces a cut somewhere.
    # It should land after the comma, not in the middle of the second phrase.
    text = "قال لي امس انه بيجي بدري الصبح، بس للحين ما شفته ولا رد على جواله ابد"
    cues = build_cues(words_from(text), RULES)
    assert cues[0].text.endswith("الصبح،")
    assert " ".join(c.text for c in cues) == text
