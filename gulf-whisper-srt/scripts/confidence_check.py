"""Do Whisper's low-confidence words point at the real mistakes?

The QC report flags words Whisper gave a low probability. This checks, on the clips that
have a reference transcript, whether those flagged words are wrong more often than the rest.

    python scripts/confidence_check.py results/large-v3-turbo-cuda

A word counts as wrong if, after Arabic normalization, it was not matched to the same word
in the reference (it was substituted or inserted). Missed words can't be flagged, because
there is no word to put a probability on, so they are left out of this check.
"""

import argparse
import json
import sys
from pathlib import Path

from gulf_srt.evaluate import matched_hypothesis, normalize
from gulf_srt.transcript import load_transcript

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def scored_words(run: Path, clip: str) -> list[tuple[float, bool]]:
    """(probability, is_wrong) for every Whisper word in one clip."""
    words = load_transcript(run / f"{clip}.words.json").words
    reference = normalize((SAMPLES / f"{clip}.ref.txt").read_text(encoding="utf-8-sig")).split()
    tokens, owner = [], []  # one Whisper word can normalize to 0, 1 or 2 tokens
    for k, w in enumerate(words):
        for token in normalize(w.text).split():
            tokens.append(token)
            owner.append(k)
    matched = matched_hypothesis(reference, tokens)
    wrong = [False] * len(words)
    for k, ok in zip(owner, matched):
        wrong[k] = wrong[k] or not ok
    return [(w.probability, bad) for w, bad in zip(words, wrong) if normalize(w.text)]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("run", help="a results folder with .words.json files")
    parser.add_argument("--thresholds", default="0.3,0.5,0.7")
    args = parser.parse_args()
    run = Path(args.run)
    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))

    print("| Variety | Flag words below | Words flagged | Wrong among flagged | Wrong among the rest | Share of all wrong words caught |")
    print("|---|---|---|---|---|---|")
    for variety in dict.fromkeys(c["variety"] for c in manifest if c["has_reference"]):
        words = [sw for c in manifest if c["variety"] == variety and c["has_reference"] for sw in scored_words(run, c["id"])]
        total_wrong = sum(bad for _, bad in words)
        for threshold in map(float, args.thresholds.split(",")):
            flagged = [bad for p, bad in words if p < threshold]
            rest = [bad for p, bad in words if p >= threshold]
            print(
                f"| {variety} | {threshold:.1f} | {len(flagged)}/{len(words)} ({len(flagged) / len(words):.0%}) "
                f"| {sum(flagged) / max(len(flagged), 1):.0%} | {sum(rest) / max(len(rest), 1):.0%} "
                f"| {sum(flagged)}/{total_wrong} ({sum(flagged) / max(total_wrong, 1):.0%}) |"
            )


if __name__ == "__main__":
    main()
