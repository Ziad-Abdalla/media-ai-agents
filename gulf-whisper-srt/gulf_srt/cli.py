"""Command line: python -m gulf_srt input.mp4 -o out.srt --model large-v3-turbo"""

import argparse
import time
from pathlib import Path

from gulf_srt.segment import Rules, build_cues
from gulf_srt.srt import write_srt
from gulf_srt.transcribe import load_model, transcribe


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Arabic audio/video to Arabic SRT subtitles.")
    parser.add_argument("input", help="audio or video file (mp4, mov, wav, mp3, ...)")
    parser.add_argument("-o", "--output", help="output .srt (default: next to the input)")
    parser.add_argument("--model", default="large-v3-turbo", help="Whisper model name")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--max-line-chars", type=int, default=42)
    parser.add_argument("--no-rtl-marks", action="store_true", help="don't add U+200F marks")
    args = parser.parse_args(argv)

    output = Path(args.output) if args.output else Path(args.input).with_suffix(".srt")

    model, device = load_model(args.model, args.device)
    started = time.perf_counter()
    words, duration = transcribe(model, args.input)
    cues = build_cues(words, Rules(max_line_chars=args.max_line_chars))
    write_srt(cues, output, rtl=not args.no_rtl_marks)
    elapsed = time.perf_counter() - started

    speed = elapsed / duration if duration else 0.0
    print(f"{len(cues)} cues -> {output}")
    print(f"{duration:.1f} s of audio in {elapsed:.1f} s on {device} (real-time factor {speed:.3f})")


if __name__ == "__main__":
    main()
