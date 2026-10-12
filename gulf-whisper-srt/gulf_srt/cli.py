"""Command line: python -m gulf_srt input.mp4 -o out.srt --model large-v3-turbo"""

import argparse
import time
from pathlib import Path

from gulf_srt.segment import Rules, build_cues, hard_to_read
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
    output.parent.mkdir(parents=True, exist_ok=True)  # before the long transcription, not after

    model, device = load_model(args.model, args.device)
    started = time.perf_counter()
    words, duration = transcribe(model, args.input)
    rules = Rules(max_line_chars=args.max_line_chars)
    cues = build_cues(words, rules)
    write_srt(cues, output, rtl=not args.no_rtl_marks)
    elapsed = time.perf_counter() - started

    rtf = elapsed / duration if duration else 0.0
    print(f"{len(cues)} cues -> {output}")
    print(f"{duration:.1f} s of audio in {elapsed:.1f} s on {device} (real-time factor {rtf:.3f})")
    flagged = hard_to_read(cues, rules)
    if flagged:
        print(f"Check these cues, the speech was too fast or back-to-back to meet the "
              f"{rules.min_duration:g} s / {rules.max_cps:g} characters-per-second targets: "
              + ", ".join(map(str, flagged)))


if __name__ == "__main__":
    main()
