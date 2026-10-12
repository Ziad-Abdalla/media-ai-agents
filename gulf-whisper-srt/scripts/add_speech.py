"""Add speech-activity data to .words.json files saved before the QC report used it.

New runs of python -m gulf_srt save it already. This runs only the voice-activity detector
(VAD, a small model bundled with faster-whisper) on the original audio, not Whisper, so the
words, times and scores in the file don't change:

    python scripts/add_speech.py results/large-v3-turbo-cuda/*.words.json
"""

import argparse
import sys
from pathlib import Path

from gulf_srt.transcribe import detect_speech
from gulf_srt.transcript import load_transcript, save_transcript


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help=".words.json files")
    args = parser.parse_args()
    for file in args.files:
        transcript = load_transcript(file)
        if not Path(transcript.source).exists():
            print(f"{file}: media {transcript.source!r} not found, skipped", file=sys.stderr)
            continue
        transcript.speech = detect_speech(transcript.source)
        save_transcript(transcript, file)
        heard = sum(end - start for start, end in transcript.speech)
        print(f"{file}: {len(transcript.speech)} stretches of speech, {heard:.0f} s of {transcript.duration:.0f} s")


if __name__ == "__main__":
    main()
