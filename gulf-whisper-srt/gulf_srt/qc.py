"""A QC report per file: where an editor should look first.

Three kinds of problem, in the order an editor should check them:

1. The words may be wrong. Whisper scores its own output: each word gets a probability,
   and each decoded segment gets an average log-probability, a "no speech" probability
   and a compression ratio (repetitive text compresses well, a sign Whisper got stuck
   in a loop). Low scores point at words to listen to again.
2. The subtitle is hard to read: on screen too briefly, faster than the reading-speed
   target, lines over the length limit, more than two lines, or on screen too long.
3. A long stretch with no subtitles, where dialogue may have been missed (music under
   speech, people talking over each other).

Run it on our own output, or on any SRT (for example a vendor's delivery):

    python -m gulf_srt.qc out/episode01.srt --words out/episode01.words.json
    python -m gulf_srt.qc delivered/episode01.srt
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from gulf_srt.segment import Cue, Rules, Word
from gulf_srt.srt import format_timestamp, read_srt
from gulf_srt.transcript import SpeechSegment, load_transcript

LOOK_FIRST, READABILITY, MISSING = 1, 2, 3
PRIORITY_NAMES = {LOOK_FIRST: "words may be wrong", READABILITY: "hard to read", MISSING: "possible missed dialogue"}


@dataclass(frozen=True)
class QcRules:
    low_word_prob: float = 0.5  # a word Whisper gave less than this is worth a listen
    low_logprob: float = -1.0  # Whisper's own line for an unsure segment
    high_no_speech: float = 0.6  # Whisper thinks this may not be speech (music, noise)
    high_compression: float = 2.4  # Whisper's own line for repetitive, looping text
    long_silence: float = 10.0  # seconds with no subtitle before we ask "was dialogue missed?"


@dataclass
class Issue:
    priority: int
    kind: str
    start: float
    end: float
    cue: int | None  # the cue number in the SRT, from 1; None for a gap between cues
    detail: str


def words_by_cue(cues: list[Cue], words: list[Word]) -> list[list[Word]]:
    """Give each cue back its Whisper words. Cue text is the words joined by spaces, in order,
    so we walk both lists together, counting space-separated pieces."""
    result, i = [], 0
    for cue in cues:
        needed, taken = len(cue.text.split()), []
        while needed > 0 and i < len(words):
            taken.append(words[i])
            needed -= len(words[i].text.split())
            i += 1
        result.append(taken)
    return result


def _overlapping(segments: list[SpeechSegment], cue: Cue) -> list[SpeechSegment]:
    return [s for s in segments if s.start < cue.end and s.end > cue.start]


def check(
    cues: list[Cue],
    rules: Rules = Rules(),
    qc: QcRules = QcRules(),
    words: list[Word] | None = None,
    segments: list[SpeechSegment] | None = None,
    duration: float | None = None,
) -> list[Issue]:
    if words and " ".join(w.text for w in words) != " ".join(c.text for c in cues):
        raise ValueError("the words don't match the subtitles (was the SRT edited after it was made?)")
    issues: list[Issue] = []
    cue_words = words_by_cue(cues, words) if words else [[] for _ in cues]
    for n, (cue, own_words) in enumerate(zip(cues, cue_words), start=1):
        def add(priority: int, kind: str, detail: str) -> None:
            issues.append(Issue(priority, kind, cue.start, cue.end, n, detail))

        # 1. The words may be wrong.
        unsure = [w for w in own_words if w.probability < qc.low_word_prob]
        if unsure:
            listed = "، ".join(f"«{w.text}» {w.probability:.2f}" for w in unsure)
            add(LOOK_FIRST, "unsure-words", f"Whisper was unsure of: {listed}")
        for s in _overlapping(segments or [], cue):
            if s.no_speech_prob > qc.high_no_speech:
                add(LOOK_FIRST, "maybe-not-speech",
                    f"no-speech probability {s.no_speech_prob:.2f}: music, noise or a song may have been written as words")
            if s.compression_ratio > qc.high_compression:
                add(LOOK_FIRST, "repetition", f"compression ratio {s.compression_ratio:.1f}: repeated text, Whisper may be looping")
            if s.avg_logprob < qc.low_logprob and not unsure:
                add(LOOK_FIRST, "unsure-segment", f"average log-probability {s.avg_logprob:.2f} for the whole phrase")

        # 2. Hard to read.
        duration_on_screen = cue.end - cue.start
        if duration_on_screen < rules.min_duration - 1e-6:
            add(READABILITY, "too-short", f"on screen {duration_on_screen:.2f} s (target at least {rules.min_duration:g} s)")
        if duration_on_screen <= 0 or len(cue.text) / duration_on_screen > rules.max_cps + 1e-6:
            cps = len(cue.text) / duration_on_screen if duration_on_screen > 0 else float("inf")
            add(READABILITY, "too-fast", f"{cps:.0f} characters per second (target at most {rules.max_cps:g})")
        if duration_on_screen > rules.max_duration + 1e-6:
            add(READABILITY, "too-long", f"on screen {duration_on_screen:.1f} s (at most {rules.max_duration:g} s)")
        long_lines = [line for line in cue.lines if len(line) > rules.max_line_chars]
        if long_lines:
            add(READABILITY, "line-too-long",
                f"{max(map(len, long_lines))} characters on one line (at most {rules.max_line_chars})")
        if len(cue.lines) > 2:
            add(READABILITY, "too-many-lines", f"{len(cue.lines)} lines (at most 2)")

    # 3. Long stretches with no subtitle: the start of the file, between cues, and the end.
    edges = [0.0] + [t for c in cues for t in (c.start, c.end)] + [duration if duration else (cues[-1].end if cues else 0.0)]
    for gap_start, gap_end in zip(edges[0::2], edges[1::2]):
        if gap_end - gap_start >= qc.long_silence:
            issues.append(Issue(MISSING, "long-silence", gap_start, gap_end, None,
                                f"{gap_end - gap_start:.0f} s with no subtitle: check for missed dialogue"))

    issues.sort(key=lambda i: (i.priority, i.start))
    return issues


def summary(cues: list[Cue], issues: list[Issue]) -> dict:
    flagged = {i.cue for i in issues if i.cue is not None}
    kinds: dict[str, int] = {}
    for issue in issues:
        kinds[issue.kind] = kinds.get(issue.kind, 0) + 1
    return {
        "cues": len(cues),
        "cues_flagged": len(flagged),
        "share_flagged": round(len(flagged) / len(cues), 3) if cues else 0.0,
        "by_kind": kinds,
    }


def to_markdown(cues: list[Cue], issues: list[Issue], title: str, has_confidence: bool) -> str:
    s = summary(cues, issues)
    out = [
        f"# QC report: {title}",
        "",
        f"{s['cues']} subtitles, {s['cues_flagged']} flagged ({s['share_flagged']:.0%}). "
        "Check them in the order below: words that may be wrong first, then readability, then gaps.",
    ]
    if not has_confidence:
        out += ["", "No Whisper confidence data was given (for example, a delivered SRT), so only "
                "readability and gaps are checked."]
    if not issues:
        return "\n".join(out + ["", "Nothing to flag."]) + "\n"
    out += ["", "| Check | Time | Cue | Problem | Detail | Text |", "|---|---|---|---|---|---|"]
    for i, issue in enumerate(issues, start=1):
        text = cues[issue.cue - 1].text if issue.cue else ""
        cue = str(issue.cue) if issue.cue else "gap"
        out.append(f"| {i} | {format_timestamp(issue.start)} | {cue} | {PRIORITY_NAMES[issue.priority]}: "
                   f"{issue.kind} | {issue.detail} | {text} |")
    return "\n".join(out) + "\n"


def to_json(cues: list[Cue], issues: list[Issue]) -> str:
    return json.dumps({"summary": summary(cues, issues), "issues": [asdict(i) for i in issues]},
                      ensure_ascii=False, indent=1)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="QC report for a subtitle file.")
    parser.add_argument("srt")
    parser.add_argument("--words", help="the .words.json saved by python -m gulf_srt (adds confidence checks)")
    parser.add_argument("-o", "--output", help="where to write the .qc.md (default: next to the SRT)")
    parser.add_argument("--max-line-chars", type=int, default=42)
    args = parser.parse_args(argv)

    cues = read_srt(args.srt)
    transcript = load_transcript(args.words) if args.words else None
    rules = Rules(max_line_chars=args.max_line_chars)
    if transcript:
        try:
            issues = check(cues, rules, words=transcript.words, segments=transcript.segments,
                           duration=transcript.duration)
        except ValueError as error:  # an edited SRT: word-level scores no longer line up
            print(f"Not using word confidence: {error}", file=sys.stderr)
            issues = check(cues, rules, segments=transcript.segments, duration=transcript.duration)
    else:
        issues = check(cues, rules)
    output = Path(args.output) if args.output else Path(args.srt).with_suffix(".qc.md")
    output.write_text(to_markdown(cues, issues, Path(args.srt).name, transcript is not None), encoding="utf-8")
    output.with_suffix(".json").write_text(to_json(cues, issues), encoding="utf-8")
    s = summary(cues, issues)
    print(f"{s['cues_flagged']} of {s['cues']} subtitles flagged -> {output}")


if __name__ == "__main__":
    main()
