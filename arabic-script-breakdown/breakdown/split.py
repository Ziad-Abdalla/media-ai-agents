"""Split a screenplay into scenes. Plain rules, no AI.

Writers number their scenes in many ways:
    مشهد ١ -      م/2 -      م.13 -      مشهد (3) -      ٥ -
and sometimes not at all:
    داخلي - نهار - بيت أبو فهد - الصالة
This file finds every heading, normalizes the digits, and gives each scene a
number. If a heading has no number, it takes the previous number + 1.
"""

import math
import re
from dataclasses import dataclass

from .normalize import normalize_digits

# "مشهد 3", "م/3", "م.3", "م 3", "مشهد (3)", or just "3 -" at the start of a line
_NUMBERED = re.compile(r"^\s*(?:مشهد|م\s*[/.]|م(?=\s*\d))?\s*\(?\s*(\d+)\s*\)?\s*[-–:.]")
_INT_EXT = re.compile(r"(?<![\w])(داخلي|خارجي)(?![\w])")
_DIALOGUE = re.compile(r"^[^:\-–]{1,30}:")  # "فهد: ..." is dialogue, not a heading

LINES_PER_PAGE = 55  # a rough screenplay page


@dataclass
class Scene:
    number: int
    heading: str
    text: str  # heading + body

    @property
    def length_eighths(self) -> int:
        """Length in eighths of a page, the unit schedulers use. Minimum 1/8."""
        lines = [line for line in self.text.splitlines() if line.strip()]
        return max(1, math.ceil(len(lines) / (LINES_PER_PAGE / 8)))


def is_heading(line: str) -> bool:
    line = normalize_digits(line.strip())
    if not line or len(line) > 120 or not _INT_EXT.search(line):
        return False
    if _NUMBERED.match(line):  # "مشهد ٥ - داخلي ..." or "مشهد 5: داخلي ..."
        return True
    if _DIALOGUE.match(line):  # "فهد: نروح داخلي - ولا - برا؟" is someone talking
        return False
    return line.count(" - ") >= 2  # unnumbered, but built like one: "داخلي - نهار - مكان"


def heading_number(line: str) -> int | None:
    match = _NUMBERED.match(normalize_digits(line.strip()))
    return int(match.group(1)) if match else None


# Time words in a heading. "آخر الليل" is still night.
_TIMES = {"نهار": "نهار", "ليل": "ليل", "آخر الليل": "ليل", "فجر": "فجر", "غروب": "غروب"}


def heading_time(heading: str) -> str | None:
    """The time of day written in a heading, or None (for example when it only says متصل).

    A heading is split on its dashes: "م/9 - داخلي - ليل - غرفة فهد" -> [..., "ليل", ...].
    """
    for part in re.split(r"\s[-–]\s|:", heading):
        if part.strip() in _TIMES:
            return _TIMES[part.strip()]
    return None


def split_script(script: str) -> tuple[str, list[Scene]]:
    """Return (preamble, scenes). The preamble is everything before scene 1 (title, cast list)."""
    preamble: list[str] = []
    scenes: list[Scene] = []
    current: list[str] | None = None
    heading = ""
    number = 0

    def close() -> None:
        if current is not None:
            scenes.append(Scene(number=number, heading=heading, text="\n".join(current).strip()))

    for line in script.splitlines():
        if is_heading(line):
            close()
            parsed = heading_number(line)
            number = parsed if parsed is not None else number + 1
            heading = line.strip()
            current = [line.strip()]
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    close()
    return "\n".join(preamble).strip(), scenes


def cast_list(preamble: str) -> str:
    """The lines after 'الشخصيات:' — passed to the model so it uses the right names."""
    _, _, after = preamble.partition("الشخصيات:")
    return after.split("----")[0].strip()
