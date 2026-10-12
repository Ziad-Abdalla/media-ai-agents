import pytest

from gulf_srt.evaluate import cer, edit_distance, normalize, score, wer


def test_normalize_removes_tashkeel_and_tatweel():
    assert normalize("مُحَمَّدٌ") == "محمد"
    assert normalize("مـــرحبا") == "مرحبا"


def test_normalize_unifies_letter_variants():
    assert normalize("أحمد إلى آخر المدرسة") == normalize("احمد الي اخر المدرسه")


def test_normalize_strips_punctuation_and_digits():
    assert normalize("كيفك؟ تمام، الحمد لله.") == "كيفك تمام الحمد لله"
    assert normalize("عام ٢٠٢٤") == "عام 2024"


def test_light_normalization_keeps_letter_variants():
    assert normalize("إلى", arabic=False) == "إلى"


def test_edit_distance_basics():
    assert edit_distance(list("abc"), list("abc")) == 0
    assert edit_distance(list("abc"), list("abd")) == 1  # substitution
    assert edit_distance(list("abc"), list("ab")) == 1  # deletion
    assert edit_distance(list("abc"), list("abxc")) == 1  # insertion
    assert edit_distance([], list("ab")) == 2


def test_wer_counts_word_errors():
    # 4 reference words, 1 substitution + 1 deletion = 2 errors
    assert wer("انا رايح البيت الحين", "انا رايح البيوت") == pytest.approx(2 / 4)
    assert wer("a b", "a b") == 0.0


def test_cer_counts_character_errors():
    assert cer("سلام", "سلم") == pytest.approx(1 / 4)


def test_normalization_changes_the_score():
    reference = "ذهبتُ إلى المدرسةِ"
    hypothesis = "ذهبت الى المدرسه"
    assert score(reference, hypothesis, arabic=False)["wer"] == pytest.approx(1.0)
    assert score(reference, hypothesis, arabic=True)["wer"] == 0.0
