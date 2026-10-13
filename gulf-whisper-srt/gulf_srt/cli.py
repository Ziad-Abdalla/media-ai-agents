"""Command line: python -m gulf_srt input.mp4 -o out/input.srt --model large-v3-turbo

One run writes, next to the SRT:
  <name>.srt              subtitles for Premiere, Resolve, Subtitle Edit
  <name>.vtt              the same subtitles as WebVTT, for web players
  <name>.transcript.txt   the dialogue with timecodes, one line per subtitle
  <name>.index.json       the dialogue index, searchable with python -m gulf_srt.archive
  <name>.qc.md / .qc.json the QC report: where an editor should look first
  <name>.review.html      play the episode with the subtitles and click through the QC flags
  <name>.words.json       Whisper's raw words, times, confidence and where speech was heard
                          (rebuild everything with --from-json)
"""

import argparse
import sys
import time
from pathlib import Path

from gulf_srt import archive, formats, qc, review
from gulf_srt.replace import apply_replacements, read_replacements
from gulf_srt.segment import Rules, build_cues
from gulf_srt.srt import write_srt
from gulf_srt.transcript import Transcript, load_transcript, read_hotwords, save_transcript

WORDS_SUFFIX = ".words.json"


def default_output(source: str) -> Path:
    """Where the SRT goes when -o isn't given: beside the input, with the same name.
    'Show.S01E03.words.json' -> 'Show.S01E03.srt' (only the known ending is removed, so dots
    inside episode names are kept and two episodes never write over each other)."""
    if source.endswith(WORDS_SUFFIX):
        return Path(source[: -len(WORDS_SUFFIX)] + ".srt")
    return Path(source).with_suffix(".srt")


def write_outputs(transcript: Transcript, srt_path: Path, rules: Rules, rtl: bool = True,
                  media: str | None = None) -> tuple[list, list, str]:
    """Every output file from one transcript. Returns the cues, the QC issues, and a sentence
    saying whether the review page was written (and why not, if it wasn't)."""
    stem = srt_path.with_name(srt_path.stem)  # out/Show.S01E03.srt -> out/Show.S01E03
    name = srt_path.stem
    cues = build_cues(transcript.words, rules)
    write_srt(cues, srt_path, rtl=rtl)
    formats.write_text(formats.to_vtt(cues, rtl=rtl), f"{stem}.vtt")
    formats.write_text(formats.to_transcript(cues, title=name), f"{stem}.transcript.txt")
    archive.write_index(archive.make_index(archive.entries_from_cues(cues, srt_path.name)), f"{stem}.index.json")
    issues, notes = qc.run(cues, rules, transcript)
    formats.write_text(qc.to_markdown(cues, issues, name, notes), f"{stem}.qc.md")
    formats.write_text(qc.to_json(cues, issues, notes), f"{stem}.qc.json")
    media = media or transcript.source
    if media and Path(media).exists():
        page = review.review_page(cues, issues, media, f"{stem}.review.html", name)
        formats.write_text(page, f"{stem}.review.html")
        status = f"review page -> {stem}.review.html"
    else:
        status = f"no review page: the media file {media or '(none recorded)'} was not found; pass --media to point at it"
    return cues, issues, status


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Arabic audio/video to Arabic subtitles, transcript, index and QC report.")
    parser.add_argument("input", nargs="?", help="audio or video file (mp4, mov, wav, mp3, ...)")
    parser.add_argument("-o", "--output", help="output .srt (default: next to the input); the other files go beside it")
    parser.add_argument("--model", default="large-v3-turbo", help="Whisper model name")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--hotwords", help='names and words to spell right, e.g. "عبود أبو حمد"')
    parser.add_argument("--hotwords-file", help="a file with one name or phrase per line (a show's cast list)")
    parser.add_argument("--replacements", help="a show's correction list: 'wrong => right' per line, applied before cutting")
    parser.add_argument("--from-json", help="rebuild every output from a saved .words.json, without Whisper")
    parser.add_argument("--media", help="the audio/video for the review page, if it has moved since transcription")
    parser.add_argument("--max-line-chars", type=int, default=42)
    parser.add_argument("--no-rtl-marks", action="store_true", help="don't add U+200F marks")
    args = parser.parse_args(argv)
    if not args.input and not args.from_json:
        parser.error("give an input file, or --from-json")

    source = args.input or args.from_json
    output = Path(args.output) if args.output else default_output(source)
    output.parent.mkdir(parents=True, exist_ok=True)  # before the long transcription, not after
    rules = Rules(max_line_chars=args.max_line_chars)

    if args.from_json:
        transcript = load_transcript(args.from_json)
        print(f"{len(transcript.words)} words from {args.from_json} (no transcription)")
    else:
        from gulf_srt.transcribe import load_model, transcribe  # imported here so --from-json needs no model

        hotwords = read_hotwords(args.hotwords, args.hotwords_file)
        model, device = load_model(args.model, args.device)
        started = time.perf_counter()
        transcript = transcribe(model, args.input, hotwords=hotwords)
        elapsed = time.perf_counter() - started
        save_transcript(transcript, output.with_name(output.stem + WORDS_SUFFIX))  # raw, before any replacements
        rtf = elapsed / transcript.duration if transcript.duration else 0.0
        print(f"{transcript.duration:.1f} s of audio in {elapsed:.1f} s on {device} (real-time factor {rtf:.3f})")
        if transcript.hotwords:
            print(f"hotwords: {transcript.hotwords}")

    if args.replacements:
        transcript.words, count = apply_replacements(transcript.words, read_replacements(args.replacements))
        print(f"{count} spellings fixed from {args.replacements}")

    cues, issues, review_status = write_outputs(transcript, output, rules, rtl=not args.no_rtl_marks, media=args.media)
    print(f"{len(cues)} cues -> {output} (+ .vtt, .transcript.txt, .index.json, .qc.md)")
    print(review_status)
    print(f"QC: {qc.headline(qc.summary(cues, issues))} See {output.with_suffix('.qc.md')}")


if __name__ == "__main__":
    main()
