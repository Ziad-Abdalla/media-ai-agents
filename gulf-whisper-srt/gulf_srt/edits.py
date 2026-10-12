"""What editors changed: compare the machine draft with the final, approved subtitles.

    python -m gulf_srt.edits out/ep01.srt final/ep01.srt
    python -m gulf_srt.edits out/ final/ --report edits.md --suggest suggested_fixes.txt

Given two folders, it pairs the SRT files by name. For each episode it measures:

- lines changed: the share of draft subtitles whose words the editor changed or deleted.
  A line the editor only moved in time counts as "retimed", not changed.
- word edit rate: how many word edits turn the draft into the final, per final word (the
  word error rate of the draft, scored against the final).

Both use the same Arabic normalization as the WER score: punctuation, diacritics and the
أ/ا, ة/ه, ى/ي spelling variants are ignored, so only changes a viewer would notice count.
- the words editors replaced most often, written as suggested replacement rules. They are
  written commented out, so nothing is used until a person reads and approves each one.

Editing time is not something a subtitle file can tell you; log minutes per episode for that.
"""

import argparse
import difflib
import sys
from collections import Counter
from pathlib import Path

from gulf_srt.evaluate import edit_distance, normalize
from gulf_srt.replace import split_punctuation
from gulf_srt.segment import Cue
from gulf_srt.srt import read_srt

TIMING_TOLERANCE = 0.05  # seconds; a smaller move is rounding, not a retime


def _words(text: str) -> list[str]:
    return normalize(text).split()


def _comparable(cues: list[Cue]) -> tuple[list[str], list[str]]:
    """Each word as written (without punctuation), and its normalized form for comparing."""
    raw, key = [], []
    for word in (w for c in cues for w in c.text.split()):
        core = split_punctuation(word)[1]
        if normalize(core):
            raw.append(core)
            key.append(normalize(core))
    return raw, key


def compare(draft: list[Cue], final: list[Cue]) -> dict:
    """Lines changed, lines retimed and word edit rate for one episode."""
    changed = retimed = 0
    for cue in draft:
        near = [f for f in final if f.start < cue.end and f.end > cue.start]
        said = " ".join(_words(cue.text))
        kept = bool(said) and f" {said} " in f" {' '.join(w for f in near for w in _words(f.text))} "
        if not kept:
            changed += 1
        elif not any(abs(f.start - cue.start) <= TIMING_TOLERANCE and abs(f.end - cue.end) <= TIMING_TOLERANCE
                     for f in near):
            retimed += 1
    draft_words = [w for c in draft for w in _words(c.text)]
    final_words = [w for c in final for w in _words(c.text)]
    return {
        "lines": len(draft),
        "changed": changed,
        "retimed": retimed,
        "word_edits": edit_distance(final_words, draft_words),
        "final_words": len(final_words),
    }


def replaced_words(draft: list[Cue], final: list[Cue], longest: int = 3) -> Counter:
    """Count (draft words -> final words) swaps of up to `longest` words on each side,
    written as the words appear in the files, so they can be used as replacement rules."""
    (a_raw, a), (b_raw, b) = _comparable(draft), _comparable(final)
    swaps: Counter = Counter()
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "replace" and a2 - a1 <= longest and b2 - b1 <= longest:
            swaps[(" ".join(a_raw[a1:a2]), " ".join(b_raw[b1:b2]))] += 1
    return swaps


def suggestions(swaps: Counter, episodes: dict[tuple[str, str], set], min_count: int = 2) -> str:
    """Replacement rules for a person to approve, most frequent first, all commented out."""
    out = ["# Suggested from what editors changed. Nothing here is used until a person approves it:",
           "# check each rule, delete the '# ' in front of the ones you want, and save this as the show's",
           "# replacements file (python -m gulf_srt ... --replacements this_file.txt).", ""]
    for (wrong, right), count in swaps.most_common():
        if count >= min_count:
            out += [f"# {count} times, {len(episodes[(wrong, right)])} episode(s)", f"# {wrong} => {right}", ""]
    return "\n".join(out) + "\n"


def report(rows: list[tuple[str, dict]]) -> str:
    """A short markdown table per episode, with a total, for a weekly or monthly report."""
    def line(name: str, r: dict) -> str:
        share = r["changed"] / r["lines"] if r["lines"] else 0.0
        rate = r["word_edits"] / r["final_words"] if r["final_words"] else 0.0
        return f"| {name} | {r['lines']} | {r['changed']} ({share:.0%}) | {r['retimed']} | {rate:.1%} |"

    total = {k: sum(r[k] for _, r in rows) for k in ("lines", "changed", "retimed", "word_edits", "final_words")}
    return "\n".join([
        "| Episode | Draft lines | Lines changed by the editor | Retimed only | Word edit rate |",
        "|---|---|---|---|---|",
        *(line(name, r) for name, r in rows),
        line("**All**", total),
        "",
        "Lines changed and word edit rate measure how far the draft was from the approved subtitles. "
        "Editing time is not in the files; log minutes per episode to report time saved.",
    ]) + "\n"


def pairs(draft: Path, final: Path) -> list[tuple[Path, Path]]:
    if draft.is_file():
        return [(draft, final)]
    return [(d, final / d.name) for d in sorted(draft.glob("*.srt")) if (final / d.name).exists()]


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compare draft subtitles with the editor's final ones.")
    parser.add_argument("draft", help="the machine draft .srt, or a folder of them")
    parser.add_argument("final", help="the approved .srt, or a folder with the same file names")
    parser.add_argument("--report", help="write the table as markdown here")
    parser.add_argument("--suggest", help="write suggested replacement rules here, for a person to approve")
    parser.add_argument("--min-count", type=int, default=2, help="only suggest swaps seen at least this often")
    args = parser.parse_args(argv)

    rows, swaps, episodes = [], Counter(), {}
    for draft_file, final_file in pairs(Path(args.draft), Path(args.final)):
        draft, final = read_srt(draft_file), read_srt(final_file)
        rows.append((draft_file.stem, compare(draft, final)))
        for swap, count in replaced_words(draft, final).items():
            swaps[swap] += count
            episodes.setdefault(swap, set()).add(draft_file.stem)
    if not rows:
        parser.error("no draft/final pairs found (folders are paired by file name)")

    table = report(rows)
    print(table)
    if args.report:
        Path(args.report).write_text(table, encoding="utf-8")
    if args.suggest:
        Path(args.suggest).write_text(suggestions(swaps, episodes, args.min_count), encoding="utf-8")
        print(f"suggested rules -> {args.suggest} (commented out until someone approves them)")


if __name__ == "__main__":
    main()
