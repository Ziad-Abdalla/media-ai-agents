"""Write cues as an .srt file, with right-to-left marks for Arabic lines, and read any SRT/WebVTT back."""

import html
import re
import sys
from pathlib import Path

from gulf_srt.segment import Cue

# U+200F RIGHT-TO-LEFT MARK: an invisible character that counts as a right-to-left letter.
RLM = "\u200f"

# Arabic letters: the main block, Supplement, Extended-A, and the two presentation-form
# blocks (ending at FEFC, so the invisible U+FEFF byte-order mark doesn't count as Arabic).
_ARABIC = re.compile("[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufefc]")


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
    """Keep only the spoken text of an SRT (drop numbers, timings, RLM marks).

    Each block is a number line, a timing line, then the text lines, with an empty
    line between blocks. We skip the first two lines of every block (not "any line
    that is a number"), so a subtitle line that is just "2024" is kept."""
    text_lines = []
    line_in_block = 0
    for line in srt.splitlines():
        line = line.replace(RLM, "").strip()
        if not line:  # an empty line ends the block
            line_in_block = 0
            continue
        line_in_block += 1
        if line_in_block > 2:
            text_lines.append(line)
    return " ".join(text_lines)


# hh:mm:ss,mmm --> hh:mm:ss,mmm. The hours are optional, because WebVTT allows mm:ss.mmm
# (common in files from YouTube and web tools). Anything after the end time (WebVTT cue
# settings like "align:start") is ignored.
_TIME = r"(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})"
_TIMING = re.compile(_TIME + r"\s*-->\s*" + _TIME)


def _seconds(hours: str | None, minutes: str, secs: str, ms: str) -> float:
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(secs) + int(ms) / 1000


# Invisible direction marks (LRM, RLM, the Arabic letter mark, and the embedding, override and
# isolate controls). They don't show on screen, so they must not count as characters.
_BIDI = re.compile("[\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]")
# Formatting that players draw but don't show as text: <i>, </b>, <font color=...>, WebVTT's
# <c.yellow> and <v Speaker>, and positioning like {\an8}.
_TAGS = re.compile(r"</?[a-zA-Z][^<>]*>|\{\\[^{}]*\}")


def clean_line(line: str, webvtt: bool = False) -> str:
    """The text a viewer reads: no tags, no direction marks, and WebVTT's &amp; back to &."""
    line = _TAGS.sub("", _BIDI.sub("", line))
    return (html.unescape(line) if webvtt else line).strip()


def parse_srt(srt: str) -> list[Cue]:
    """Read an SRT or WebVTT file (ours or anyone's, for example a delivered subtitle file) back into cues.

    Blocks are separated by empty lines; in each block we look for the timing line and keep
    the lines after it as text, cleaned by clean_line(), so tags and direction marks don't count
    towards line length or reading speed. Blocks with no timing line (like the WEBVTT header)
    are skipped. A block that has "-->" but a timing we can't read is skipped with a warning,
    so a line is never lost silently."""
    srt = srt.replace("\r\n", "\n").lstrip("\ufeff")
    webvtt = srt.startswith("WEBVTT")
    cues = []
    for block in re.split(r"\n\s*\n", srt):
        lines = [clean_line(line, webvtt) for line in block.strip().split("\n")]
        for i, line in enumerate(lines):
            match = _TIMING.search(line)
            if match:
                parts = match.groups()
                start, end = _seconds(*parts[:4]), _seconds(*parts[4:])
                text = [t for t in lines[i + 1 :] if t]
                if text:
                    cues.append(Cue(start, end, text))
                break
            if "-->" in line:
                print(f"Skipped a subtitle with a timing line that couldn't be read: {line!r}", file=sys.stderr)
                break
    return cues


def read_srt(path: str | Path) -> list[Cue]:
    """UTF-8 first. Older Arabic subtitle files are often Windows-1256 (cp1256), so if the file
    isn't valid UTF-8 it is read as cp1256, with a warning to check the Arabic looks right."""
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1256", errors="replace")
        print(f"{path} is not UTF-8; read it as Windows-1256 (cp1256). Check the Arabic looks right.",
              file=sys.stderr)
    return parse_srt(text)
