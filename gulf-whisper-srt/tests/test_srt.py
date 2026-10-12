import unicodedata

from gulf_srt.segment import Cue
from gulf_srt.srt import RLM, format_timestamp, parse_srt, rtl_line, srt_to_text, to_srt


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
    cues = [Cue(0.0, 2.0, ["Netflix 2024", "إنتاج درامي سعودي"])]
    lines = to_srt(cues).splitlines()
    assert lines[2] == "Netflix 2024"
    assert first_strong_direction(lines[3]) == "rtl"


def test_srt_to_text_round_trip():
    cues = [Cue(0.0, 2.0, ["هلا والله", "كيفك؟"]), Cue(3.0, 4.0, ["تمام"])]
    assert srt_to_text(to_srt(cues)) == "هلا والله كيفك؟ تمام"


def test_srt_to_text_keeps_a_line_that_is_only_a_number():
    cues = [Cue(0.0, 2.0, ["في سنة", "2024"]), Cue(3.0, 4.0, ["تمام"])]
    assert srt_to_text(to_srt(cues)) == "في سنة 2024 تمام"


def test_parse_srt_round_trip_with_marks():
    cues = [Cue(0.0, 2.0, ["هلا والله", "كيفك؟"]), Cue(3.5, 4.25, ["2024"])]
    back = parse_srt(to_srt(cues))
    assert [(c.start, c.end, c.lines) for c in back] == [(c.start, c.end, c.lines) for c in cues]


def test_parse_srt_handles_windows_line_endings_and_bom():
    text = "﻿1\r\n00:00:01,000 --> 00:00:02,500\r\nتمام\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nزين\r\n"
    assert [c.text for c in parse_srt(text)] == ["تمام", "زين"]


def test_webvtt_without_hours_and_with_cue_settings():
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.500 align:start\nهلا\n\n01:02:03.000 --> 01:02:04.000\nزين\n"
    assert [(c.start, c.end, c.text) for c in parse_srt(vtt)] == [(1.0, 2.5, "هلا"), (3723.0, 3724.0, "زين")]


def test_a_timing_line_that_cannot_be_read_is_reported(capsys):
    assert parse_srt("1\n00:00:01 --> 00:00:02\nهلا\n") == []
    assert "couldn't be read" in capsys.readouterr().err
