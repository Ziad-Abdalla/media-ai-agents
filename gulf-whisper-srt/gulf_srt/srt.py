"""Write cues as an .srt file, with right-to-left marks for Arabic lines."""

import re
from pathlib import Path

from gulf_srt.segment import Cue

# U+200F RIGHT-TO-LEFT MARK: an invisible character that counts as a right-to-left letter.
RLM = "‏"

_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def format_timestamp(seconds: float) -> str:
    """12.5 -> '00:00:12,500' (SRT uses a comma before the milliseconds)."""
    total_ms = round(seconds * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def rtl_line(line: str) -> str:
    """Wrap an Arabic line in RLM marks.

    Players guess a line's direction from its first strong letter, and
    neutral characters like '.' or '؟' at the edges follow their neighbours,
    so the marks keep a line that starts with a Latin word like 'Netflix', or ends
    with punctuation, laid out right-to-left. The text itself is unchanged.
    """
    if _ARABIC.search(line):
        return RLM + line + RLM
    return line


def to_srt(cues: list[Cue], rtl: bool = True) -> str:
    blocks = []
    for number, cue in enumerate(cues, start=1):
        lines = [rtl_line(line) if rtl else line for line in cue.lines]
        timing = f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}"
        blocks.append("\n".join([str(number), timing, *lines]))
    return "\n\n".join(blocks) + "\n"


def write_srt(cues: list[Cue], path: str | Path, rtl: bool = True) -> None:
    Path(path).write_text(to_srt(cues, rtl), encoding="utf-8")


def srt_to_text(srt: str) -> str:
    """Keep only the spoken text of an SRT (drop numbers, timings, RLM marks)."""
    text_lines = []
    for line in srt.splitlines():
        line = line.replace(RLM, "").strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        text_lines.append(line)
    return " ".join(text_lines)
