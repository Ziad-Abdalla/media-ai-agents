import pytest

from gulf_srt.replace import apply_replacements, read_replacements
from gulf_srt.segment import Word


def words(text, probability=0.9):
    return [Word(float(i), i + 1.0, w, probability) for i, w in enumerate(text.split())]


def texts(result):
    return " ".join(w.text for w in result[0])


def test_file_format_and_bad_lines(tmp_path):
    file = tmp_path / "fixes.txt"
    file.write_text("# show fixes\n\nابو حمد => أبو حمد\nعلى شأن => علشان\n", encoding="utf-8")
    assert read_replacements(file) == [(["ابو", "حمد"], "أبو حمد"), (["على", "شأن"], "علشان")]
    file.write_text("عبود أبو حمد\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        read_replacements(file)


def test_whole_words_only_with_attached_letters_and_punctuation_kept():
    rules = [(["عبوود"], "عبود")]
    assert texts(apply_replacements(words("يا عبوود، ولعبوود معبوود"), rules)) == "يا عبود، ولعبود معبوود"


def test_two_words_become_one_with_their_time_span_and_lowest_score():
    result, count = apply_replacements(words("أنا أقوم بدري على شأن الرياضة") + [], [(["على", "شأن"], "علشان")])
    fixed = [w for w in result if w.text == "علشان"][0]
    assert (fixed.start, fixed.end, count) == (3.0, 5.0, 1)
    low = words("على شأن")
    low[1].probability = 0.2
    assert apply_replacements(low, [(["على", "شأن"], "علشان")])[0][0].probability == 0.2


def test_no_match_across_the_end_of_a_sentence():
    assert texts(apply_replacements(words("رحت على. شأن"), [(["على", "شأن"], "علشان")])) == "رحت على. شأن"


def test_a_name_that_is_already_right_is_not_counted():
    assert apply_replacements(words("يا عبود"), [(["عبود"], "عبود")])[1] == 0


def test_short_rules_never_change_other_words_that_start_with_an_attached_letter():
    rules = [(["ريم"], "ريما"), (["مال"], "أموال"), (["حمد"], "أحمد")]
    text = "كريم وكمال قالوا بحمد الله الحمد لله"
    assert texts(apply_replacements(words(text), rules)) == text
    assert texts(apply_replacements(words("يا ريم، مال"), rules)) == "يا ريما، أموال"


def test_an_attached_form_of_a_short_word_needs_its_own_rule():
    rules = [(["ريم"], "ريما"), (["لريم"], "لريما")]
    assert texts(apply_replacements(words("قل لريم"), rules)) == "قل لريما"
