from pathlib import Path

import pytest

from breakdown.split import cast_list, heading_number, is_heading, split_script

SCRIPT = Path(__file__).parent.parent / "data" / "kamera_jaddi.txt"


@pytest.mark.parametrize("line, number", [
    ("مشهد ١ - داخلي/خارجي - نهار - سيارة أبو فهد", 1),   # Arabic-Indic digit
    ("م/2 - داخلي - نهار - فصل ٣ ثانوي", 2),              # م/ short form, Western digit
    ("مشهد (3) - داخلي - نهار - ممر المدرسة", 3),          # number in brackets
    ("٥ - خارجي - نهار - ساحة المدرسة", 5),               # number only, no word مشهد
    ("م.13 - خارجي - فجر - سطح بيت أبو فهد", 13),          # م. short form
    ("م/١٩ - داخلي - آخر الليل - غرفة فهد", 19),
    ("مشهد 7: داخلي - ليل - المجلس", 7),                  # colon after the number
])
def test_numbered_headings(line, number):
    assert is_heading(line)
    assert heading_number(line) == number


def test_unnumbered_heading_is_still_a_heading():
    line = "داخلي - نهار - بيت أبو فهد - الصالة"
    assert is_heading(line)
    assert heading_number(line) is None


@pytest.mark.parametrize("line", [
    "فهد: ابشر يبه.",                                   # dialogue
    "ماجد: نروح داخلي - ولا - برا؟",                     # dialogue that looks like a heading
    "داخل السيارة: أبو فهد خلف المقود.",                 # "داخل" is not "داخلي"
    "الشمس تنزل على جدران الطين.",                       # action line
    "",
])
def test_not_headings(line):
    assert not is_heading(line)


def test_unnumbered_scene_gets_previous_plus_one():
    script = "عنوان\nمشهد ٤ - داخلي - نهار - مكان\nنص\nداخلي - ليل - مكان آخر - غرفة\nنص"
    _, scenes = split_script(script)
    assert [s.number for s in scenes] == [4, 5]


def test_real_script_has_26_scenes_in_order():
    preamble, scenes = split_script(SCRIPT.read_text(encoding="utf-8"))
    assert [s.number for s in scenes] == list(range(1, 27))
    assert "كاميرا جدّي" in preamble
    assert all(s.length_eighths >= 1 for s in scenes)


def test_cast_list_comes_from_preamble():
    preamble, _ = split_script(SCRIPT.read_text(encoding="utf-8"))
    cast = cast_list(preamble)
    assert "الجدة لطيفة" in cast
    assert "----" not in cast


def test_repeated_scene_number_warns():
    script = "مشهد 4 - داخلي - نهار - مكان\nنص\nمشهد 4 - خارجي - ليل - مكان آخر\nنص"
    with pytest.warns(UserWarning, match="scene number 4 comes after 4"):
        split_script(script)
