"""A QC report per file: where an editor should look first.

Four kinds of problem, ranked by what costs most if it goes out unchecked:

1. Dialogue may be missing. The voice-activity detector (VAD) heard speech, but no subtitle
   covers it: Whisper skipped or dropped it. Whisper's own scores can't show this (there is
   no word to score), so it goes first, the stretch with the most speech first. Without
   speech data (for example a delivered SRT), any 10 s stretch with no subtitle is listed
   here instead, because we can't tell speech from music. The end of a delivered SRT is only
   checked if you give the episode length with --duration; otherwise a file missing its
   last act would pass.
2. The words may be wrong. Whisper scores its own output: each word gets a probability,
   and each 30-second window it decodes gets an average log-probability, a "no speech"
   probability and a compression ratio (repetitive text compresses well, a sign Whisper got
   stuck in a loop). Low scores point at words to listen to again.
3. The subtitle is hard to read: on screen too briefly, faster than the reading-speed
   target, lines over the length limit, more than two lines, or on screen too long.
4. A long stretch with no subtitle where the VAD heard little speech (music, silence):
   a quick check.

Run it on our own output, or on any SRT (for example a vendor's delivery):

    python -m gulf_srt.qc out/episode01.srt --words out/episode01.words.json
    python -m gulf_srt.qc delivered/episode01.srt --duration 44:30
"""

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from gulf_srt.replace import apply_replacements, read_replacements
from gulf_srt.segment import Cue, Rules, Word
from gulf_srt.srt import format_timestamp, read_srt
from gulf_srt.transcript import SpeechSegment, Transcript, load_transcript

MAYBE_MISSING, MAYBE_WRONG, READABILITY, QUIET_GAP = 1, 2, 3, 4
PRIORITY_NAMES = {
    MAYBE_MISSING: "dialogue may be missing",
    MAYBE_WRONG: "words may be wrong",
    READABILITY: "hard to read",
    QUIET_GAP: "long gap, little speech heard",
}
WINDOW_KINDS = {"maybe-not-speech", "repetition", "unsure-segment"}

# What the report says when a check could not run.
NOTES = {
    "edited": "Word confidence is off: this SRT was edited after it was made, so Whisper's words no "
              "longer line up with it. Readability, gaps and Whisper's window scores still ran.",
    "no-words": "No Whisper data was given (for example, a delivered SRT), so only readability and "
                "gaps are checked, and gaps are judged by length only.",
    "no-speech": "This words.json has no speech-activity data, so gaps are judged by length only.",
    "no-end": "The episode length wasn't given, so the stretch after the last subtitle was not checked. "
              "Pass --duration (for example --duration 44:30) to check the end of the file too.",
}


@dataclass(frozen=True)
class QcRules:
    low_word_prob: float = 0.5  # a word Whisper gave less than this is worth a listen
    low_logprob: float = -1.0  # Whisper's own line for an unsure window
    high_no_speech: float = 0.6  # Whisper thinks this may not be speech (music, noise)
    high_compression: float = 2.4  # Whisper's own line for repetitive, looping text
    missed_speech: float = 3.0  # seconds of heard speech with no subtitle before we flag it
    long_silence: float = 10.0  # seconds with no subtitle worth a look even if no speech was heard


@dataclass
class Issue:
    priority: int
    kind: str
    start: float
    end: float
    cue: int | None  # the cue number in the SRT, from 1; None for a gap between cues
    detail: str
    speech_seconds: float = 0.0  # for gaps: how much speech the VAD heard in it (ranks the gaps)


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


def decode_windows(segments: list[SpeechSegment]) -> list[tuple[float, float, SpeechSegment]]:
    """Group segments back into the windows Whisper decoded in one go. Neighbouring segments
    from one window carry identical scores, so a run of identical scores is one window."""
    windows: list[tuple[float, float, SpeechSegment]] = []
    for s in segments:
        if windows:
            w_start, _, first = windows[-1]
            if (s.avg_logprob, s.no_speech_prob, s.compression_ratio) == (
                    first.avg_logprob, first.no_speech_prob, first.compression_ratio):
                windows[-1] = (w_start, s.end, first)
                continue
        windows.append((s.start, s.end, s))
    return windows


def _overlap(start: float, end: float, spans: list[list[float]]) -> float:
    """Seconds of the spans that fall between start and end."""
    return sum(max(0.0, min(end, s_end) - max(start, s_start)) for s_start, s_end in spans)


def _shown(probability: float) -> str:
    """Rounded down, so a word under the 0.5 line never prints as 0.50."""
    return f"{math.floor(probability * 100) / 100:.2f}"


def _cue_checks(cues: list[Cue], cue_words: list[list[Word]], rules: Rules, qc: QcRules) -> list[Issue]:
    issues: list[Issue] = []
    for n, (cue, own_words) in enumerate(zip(cues, cue_words), start=1):
        def add(priority: int, kind: str, detail: str) -> None:
            issues.append(Issue(priority, kind, cue.start, cue.end, n, detail))

        unsure = [w for w in own_words if w.probability < qc.low_word_prob]
        if unsure:
            listed = ", ".join(f"«{w.text}» {_shown(w.probability)}" for w in unsure)
            add(MAYBE_WRONG, "unsure-words", f"Whisper was unsure of: {listed}")

        on_screen = cue.end - cue.start
        if on_screen < rules.min_duration - 1e-6:
            add(READABILITY, "too-short", f"on screen {on_screen:.2f} s (target at least {rules.min_duration:g} s)")
        if on_screen <= 0 or len(cue.text) / on_screen > rules.max_cps + 1e-6:
            cps = len(cue.text) / on_screen if on_screen > 0 else float("inf")
            add(READABILITY, "too-fast", f"{cps:.0f} characters per second (target at most {rules.max_cps:g})")
        if on_screen > rules.max_duration + 1e-6:
            add(READABILITY, "too-long", f"on screen {on_screen:.1f} s (at most {rules.max_duration:g} s)")
        long_lines = [line for line in cue.lines if len(line) > rules.max_line_chars]
        if long_lines:
            add(READABILITY, "line-too-long",
                f"{max(map(len, long_lines))} characters on one line (at most {rules.max_line_chars})")
        if len(cue.lines) > 2:
            add(READABILITY, "too-many-lines", f"{len(cue.lines)} lines (at most 2)")
    return issues


def _window_checks(cues: list[Cue], segments: list[SpeechSegment], qc: QcRules) -> list[Issue]:
    """Whisper's window scores: one flag per decode window, not one per cue inside it."""
    issues: list[Issue] = []
    for start, end, s in decode_windows(segments):
        inside = [n for n, c in enumerate(cues, start=1) if c.start < end and c.end > start]
        where = f"the whole window {format_timestamp(start)[:8]}-{format_timestamp(end)[:8]}"
        if len(inside) > 1:
            where += f" (cues {inside[0]}-{inside[-1]})"
        found = []
        if s.no_speech_prob > qc.high_no_speech:
            found.append(("maybe-not-speech", f"no-speech probability {s.no_speech_prob:.2f}: music, noise "
                                              "or a song may have been written as words"))
        if s.compression_ratio > qc.high_compression:
            found.append(("repetition", f"compression ratio {s.compression_ratio:.1f}: repeated text, "
                                        "Whisper may be looping"))
        if s.avg_logprob < qc.low_logprob:
            found.append(("unsure-segment", f"average log-probability {s.avg_logprob:.2f}"))
        for kind, detail in found:
            issues.append(Issue(MAYBE_WRONG, kind, start, end, inside[0] if inside else None, f"{detail}, for {where}"))
    return issues


def _gap_checks(cues: list[Cue], duration: float | None, speech: list[list[float]] | None, qc: QcRules) -> list[Issue]:
    """Stretches with no subtitle: the start of the file, between cues, and the end."""
    issues: list[Issue] = []
    edges = [0.0] + [t for c in cues for t in (c.start, c.end)] + [duration if duration else (cues[-1].end if cues else 0.0)]
    for start, end in zip(edges[0::2], edges[1::2]):
        length = end - start
        if speech is None:  # no speech data: judge by length only
            if length >= qc.long_silence:
                issues.append(Issue(MAYBE_MISSING, "long-gap", start, end, None,
                                    f"{length:.0f} s with no subtitle: listen for missed dialogue"))
            continue
        heard = _overlap(start, end, speech)
        if heard >= qc.missed_speech:
            issues.append(Issue(MAYBE_MISSING, "missed-speech", start, end, None,
                                f"speech heard for {heard:.0f} s of a {length:.0f} s stretch with no subtitle: "
                                "dialogue was probably skipped", round(heard, 2)))
        elif length >= qc.long_silence:
            issues.append(Issue(QUIET_GAP, "quiet-gap", start, end, None,
                                f"{length:.0f} s with no subtitle and little speech heard ({heard:.0f} s): "
                                "probably music or silence", round(heard, 2)))
    return issues


def check(
    cues: list[Cue],
    rules: Rules = Rules(),
    qc: QcRules = QcRules(),
    words: list[Word] | None = None,
    segments: list[SpeechSegment] | None = None,
    duration: float | None = None,
    speech: list[list[float]] | None = None,
) -> list[Issue]:
    """All checks, most expensive first. `speech` is where the VAD heard speech; without it,
    gaps are judged by length only."""
    if words and " ".join(w.text for w in words) != " ".join(c.text for c in cues):
        raise ValueError("the words don't match the subtitles (was the SRT edited after it was made?)")
    cue_words = words_by_cue(cues, words) if words else [[] for _ in cues]
    issues = (_cue_checks(cues, cue_words, rules, qc) + _window_checks(cues, segments or [], qc)
              + _gap_checks(cues, duration, speech, qc))
    # Missing dialogue first (the stretch with most speech first), then wrong words, and so on.
    issues.sort(key=lambda i: (i.priority, -i.speech_seconds, i.start))
    return issues


def summary(cues: list[Cue], issues: list[Issue]) -> dict:
    flagged = {i.cue for i in issues if i.cue is not None}
    gaps = [i for i in issues if i.priority == MAYBE_MISSING]
    kinds: dict[str, int] = {}
    for issue in issues:
        kinds[issue.kind] = kinds.get(issue.kind, 0) + 1
    return {
        "cues": len(cues),
        "cues_flagged": len(flagged),
        "share_flagged": round(len(flagged) / len(cues), 3) if cues else 0.0,
        "gaps_to_check": len(gaps),
        "gap_seconds": round(sum(i.end - i.start for i in gaps), 1),
        "by_kind": kinds,
    }


def headline(s: dict) -> str:
    """'7 subtitles, 3 flagged (43%), plus 1 stretch with no subtitle to listen to (20 s).'"""
    text = f"{s['cues']} subtitles, {s['cues_flagged']} flagged ({s['share_flagged']:.0%})"
    if s["gaps_to_check"]:
        stretch = "stretch" if s["gaps_to_check"] == 1 else "stretches"
        text += f", plus {s['gaps_to_check']} {stretch} with no subtitle to listen to ({s['gap_seconds']:.0f} s)"
    return text + "."


def to_markdown(cues: list[Cue], issues: list[Issue], title: str, notes: list[str] = ()) -> str:
    out = [f"# QC report: {title}", "",
           headline(summary(cues, issues)) + " Check them in this order: the most expensive mistakes come first."]
    for note in notes:
        out += ["", NOTES[note]]
    if not issues:
        return "\n".join(out + ["", "Nothing to flag."]) + "\n"
    out += ["", "| Check | Time | Cue | Problem | Detail | Text |", "|---|---|---|---|---|---|"]
    for i, issue in enumerate(issues, start=1):
        # A window flag covers many cues, so it doesn't quote one cue's text.
        text = cues[issue.cue - 1].text if issue.cue and issue.kind not in WINDOW_KINDS else ""
        cue = str(issue.cue) if issue.cue else "gap"
        out.append(f"| {i} | {format_timestamp(issue.start)} | {cue} | {PRIORITY_NAMES[issue.priority]}: "
                   f"{issue.kind} | {issue.detail} | {text} |")
    return "\n".join(out) + "\n"


def to_json(cues: list[Cue], issues: list[Issue], notes: list[str] = ()) -> str:
    return json.dumps({"summary": summary(cues, issues), "notes": [NOTES[n] for n in notes],
                       "issues": [asdict(i) for i in issues]}, ensure_ascii=False, indent=1)


def run(cues: list[Cue], rules: Rules, transcript: Transcript | None = None,
        duration: float | None = None) -> tuple[list[Issue], list[str]]:
    """Check cues with whatever data there is. If the SRT was edited, the word check is
    switched off and the notes say so. `duration` is the episode length, for a delivered SRT
    (a transcript has its own). Returns the issues and the notes."""
    if transcript is None:
        return check(cues, rules, duration=duration), ["no-words"] + ([] if duration else ["no-end"])
    notes = [] if transcript.speech else ["no-speech"]
    speech = transcript.speech or None
    try:
        issues = check(cues, rules, words=transcript.words, segments=transcript.segments,
                       duration=transcript.duration, speech=speech)
    except ValueError:  # an edited SRT: word-level scores no longer line up
        issues = check(cues, rules, segments=transcript.segments, duration=transcript.duration, speech=speech)
        notes.insert(0, "edited")
    return issues, notes


def parse_duration(text: str) -> float:
    """'2670', '44:30' or '00:44:30.5' -> seconds."""
    seconds = 0.0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="QC report for a subtitle file.")
    parser.add_argument("srt")
    parser.add_argument("--words", help="the .words.json saved by python -m gulf_srt (adds confidence and speech checks)")
    parser.add_argument("--replacements", help="the replacements file the SRT was made with, if any")
    parser.add_argument("-o", "--output", help="where to write the .qc.md (default: next to the SRT)")
    parser.add_argument("--duration", type=parse_duration,
                        help="the episode length (seconds, mm:ss or hh:mm:ss), so the end of the file is checked too")
    parser.add_argument("--max-line-chars", type=int, default=42)
    args = parser.parse_args(argv)

    cues = read_srt(args.srt)
    transcript = load_transcript(args.words) if args.words else None
    if transcript and args.replacements:
        transcript.words, _ = apply_replacements(transcript.words, read_replacements(args.replacements))
    issues, notes = run(cues, Rules(max_line_chars=args.max_line_chars), transcript, args.duration)
    for note in ("edited", "no-end"):
        if note in notes:
            print(NOTES[note], file=sys.stderr)
    output = Path(args.output) if args.output else Path(args.srt).with_suffix(".qc.md")
    output.write_text(to_markdown(cues, issues, Path(args.srt).name, notes), encoding="utf-8")
    output.with_suffix(".json").write_text(to_json(cues, issues, notes), encoding="utf-8")
    print(f"QC: {headline(summary(cues, issues))} -> {output}")


if __name__ == "__main__":
    main()
