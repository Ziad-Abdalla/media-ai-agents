"""What Whisper heard, kept as plain data and saved as JSON.

Saving the raw words (with their times and Whisper's confidence) next to the outputs
means every other file (SRT, WebVTT, transcript, index, QC report) can be rebuilt later
with different rules, without running the model again:

    python -m gulf_srt --from-json out/episode01.words.json -o out/episode01.srt
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from gulf_srt.segment import Word


@dataclass
class SpeechSegment:
    """One stretch Whisper decoded in a single go (usually a phrase or sentence),
    with the three numbers Whisper uses to judge its own output."""

    start: float
    end: float
    text: str
    avg_logprob: float  # average log-probability of its tokens; below about -1 means unsure
    no_speech_prob: float  # how likely Whisper thinks this was not speech at all
    compression_ratio: float  # high (over about 2.4) means repetitive text, a sign of a loop


@dataclass
class Transcript:
    words: list[Word]
    duration: float  # length of the audio in seconds
    segments: list[SpeechSegment] = field(default_factory=list)
    source: str = ""  # the audio or video file it came from
    hotwords: str = ""  # the hotwords used, so a result can be traced back to its settings


def save_transcript(transcript: Transcript, path: str | Path) -> None:
    Path(path).write_text(json.dumps(asdict(transcript), ensure_ascii=False, indent=1), encoding="utf-8")


def load_transcript(path: str | Path) -> Transcript:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Transcript(
        words=[Word(**w) for w in data["words"]],
        duration=data["duration"],
        segments=[SpeechSegment(**s) for s in data.get("segments", [])],
        source=data.get("source", ""),
        hotwords=data.get("hotwords", ""),
    )


def read_names(file: str | Path) -> list[str]:
    """A hotwords file: one name or phrase per line; empty lines and lines starting with # are skipped."""
    lines = (line.strip() for line in Path(file).read_text(encoding="utf-8-sig").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def read_hotwords(text: str | None = None, file: str | Path | None = None) -> str:
    """Hotwords from the command line and/or a file, joined into the single string Whisper takes."""
    items = read_names(file) if file else []
    if text:
        items.append(text.strip())
    return " ".join(items)
