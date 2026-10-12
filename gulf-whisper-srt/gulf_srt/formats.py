"""The other files editors and the archive use, built from the same cues as the SRT.

- WebVTT (.vtt): the subtitle format web players and browsers read (HTML <track>).
  Same idea as SRT, with a "WEBVTT" header and a dot before the milliseconds.
- Dialogue transcript (.transcript.txt): one line per cue with its timecode, for reading
  an episode like a script or pasting into a log sheet.
"""

from pathlib import Path

from gulf_srt.segment import Cue
from gulf_srt.srt import format_timestamp, rtl_line


def vtt_timestamp(seconds: float) -> str:
    """12.5 -> '00:00:12.500' (WebVTT uses a dot where SRT uses a comma)."""
    return format_timestamp(seconds).replace(",", ".")


def _escape_vtt(line: str) -> str:
    # In WebVTT, < and & start tags and entities, so plain text must escape them.
    return line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_vtt(cues: list[Cue], rtl: bool = True) -> str:
    blocks = ["WEBVTT"]
    for number, cue in enumerate(cues, start=1):
        lines = [_escape_vtt(rtl_line(line) if rtl else line) for line in cue.lines]
        blocks.append("\n".join([str(number), f"{vtt_timestamp(cue.start)} --> {vtt_timestamp(cue.end)}", *lines]))
    return "\n\n".join(blocks) + "\n"


def timecode(seconds: float) -> str:
    """3725.9 -> '01:02:05' (whole seconds, enough to find a line in a timeline)."""
    return format_timestamp(seconds)[:8]


def to_transcript(cues: list[Cue], title: str = "") -> str:
    header = [f"# {title}"] if title else []
    header.append("# Machine draft from gulf-whisper-srt. Not checked by an editor.")
    body = [f"[{timecode(cue.start)}] {cue.text}" for cue in cues]
    return "\n".join(header + [""] + body) + "\n"


def write_text(text: str, path: str | Path) -> None:
    Path(path).write_text(text, encoding="utf-8")
