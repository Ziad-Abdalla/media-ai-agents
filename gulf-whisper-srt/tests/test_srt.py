import unicodedata

from gulf_srt.segment import Cue
from gulf_srt.srt import RLM, format_timestamp, rtl_line, srt_to_text, to_srt


def first_strong_direction(line: str) -> str:
    """How a player guesses a line's direction: the first letter that has one."""
    for ch in line:
        kind = unicodedata.bidirectional(ch)
        if kind in ("L", "R", "AL"):
            return "rtl" if kind in ("R", "AL") else "ltr"
    return "none"


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(12.5) == "00:00:12,500"
    assert format_timestamp(3725.042) == "01:02:05,042"
    assert format_timestamp(59.9996) == "00:01:00,000"  # rounding carries over


def test_srt_numbering_and_layout():
    cues = [Cue(0.0, 1.5, ["hello"]), Cue(2.0, 4.0, ["line one", "line two"])]
    assert to_srt(cues) == (
        "1\n00:00:00,000 --> 00:00:01,500\nhello\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nline one\nline two\n"
    )


def test_mixed_line_starting_with_number_is_rtl():
    line = "Netflix عرضت المسلسل سنة 2024؟"
    assert first_strong_direction(line) == "ltr"  # the problem: a player would lay this out LTR
    marked = rtl_line(line)
    assert first_strong_direction(marked) == "rtl"
    assert marked.startswith(RLM) and marked.endswith(RLM)


def test_rtl_marks_do_not_change_word_order():
    line = "شفت مسلسل Breaking Bad حلقة 5"
    assert rtl_line(line).replace(RLM, "") == line


def test_latin_only_line_is_left_alone():
    assert rtl_line("OK 123") == "OK 123"


def test_every_arabic_line_in_srt_is_marked():
    cues = [Cue(0.0, 2.0, ["Sadaf 2024", "إنتاج درامي سعودي"])]
    lines = to_srt(cues).splitlines()
    assert lines[2] == "Sadaf 2024"
    assert first_strong_direction(lines[3]) == "rtl"


def test_srt_to_text_round_trip():
    cues = [Cue(0.0, 2.0, ["هلا والله", "كيفك؟"]), Cue(3.0, 4.0, ["تمام"])]
    assert srt_to_text(to_srt(cues)) == "هلا والله كيفك؟ تمام"
