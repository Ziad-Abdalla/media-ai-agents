"""What Whisper heard, kept as plain data and saved as JSON.

Saving the raw words (with their times and Whisper's confidence) next to the outputs
means every other file (SRT, WebVTT, transcript, index, QC report) can be rebuilt later
with different rules, without running the model again:

    python -m gulf_srt --from-json out/episode01.words.json -o out/episode01.srt
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from gulf_srt.segment import Word


@dataclass
class SpeechSegment:
    """One segment of Whisper's output (usually a phrase), with the three numbers Whisper uses
    to judge its own output.

    The numbers belong to the whole 30-second window Whisper decoded in one go, not to the
    phrase: with word timestamps on, faster-whisper splits one window into several segments
    that all carry the same three numbers. The QC report groups them back into windows."""

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
    hotwords: str = ""  # the hotwords Whisper actually got, so a result can be traced to its settings
    hotwords_dropped: str = ""  # hotwords cut because the list was over Whisper's token limit
    # Where the voice-activity detector (VAD) heard speech, as [start, end] pairs in seconds.
    # The QC report compares these with the subtitles to find speech that was never written down.
    speech: list[list[float]] = field(default_factory=list)


def save_transcript(transcript: Transcript, path: str | Path) -> None:
    """Save as JSON. The media path is stored relative to the JSON file, so the folder can be moved
    or the outputs rebuilt from any working directory."""
    path = Path(path)
    data = asdict(transcript)
    if transcript.source:
        data["source"] = Path(os.path.relpath(Path(transcript.source).resolve(), path.resolve().parent)).as_posix()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_transcript(path: str | Path) -> Transcript:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return Transcript(
        words=[Word(**w) for w in data["words"]],
        duration=data["duration"],
        segments=[SpeechSegment(**s) for s in data.get("segments", [])],
        source=_find_media(data.get("source", ""), path.parent),
        hotwords=data.get("hotwords", ""),
        hotwords_dropped=data.get("hotwords_dropped", ""),
        speech=data.get("speech", []),
    )


def _find_media(source: str, json_folder: Path) -> str:
    """The saved media path is relative to the JSON file. Return a path that works from here,
    or the saved text unchanged if the file isn't there (the review page then says it's missing)."""
    if not source:
        return ""
    beside_json = json_folder / source
    return str(beside_json) if beside_json.exists() else source


def read_names(file: str | Path) -> list[str]:
    """A hotwords file: one name or phrase per line; empty lines and lines starting with # are skipped."""
    lines = (line.strip() for line in Path(file).read_text(encoding="utf-8-sig").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def read_hotwords(text: str | None = None, file: str | Path | None = None) -> list[str]:
    """Hotwords as a list of names: each line of the file is one name (so «أبو حمد» stays whole),
    and text typed on the command line counts word by word."""
    names = read_names(file) if file else []
    return names + (text.split() if text else [])
