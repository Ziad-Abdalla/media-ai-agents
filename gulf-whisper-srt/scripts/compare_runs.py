"""Compare two evaluation runs (for example without and with hotwords).

    python scripts/compare_runs.py results/large-v3-turbo-cuda results/large-v3-turbo-cuda-cast \
        --names data/hotwords/aldeerah_net_cast.txt

Prints, per clip and pooled per variety, WER and CER before and after (Arabic normalization).
With --names it also counts how often each name in the reference was written correctly,
which is what hotwords are for and what overall WER can hide.
"""

import argparse
import json
import sys
from pathlib import Path

from gulf_srt.evaluate import normalize
from gulf_srt.transcript import read_names

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def count(text: str, name: str) -> int:
    """How many times a name appears, as whole words, after Arabic normalization."""
    words, target = normalize(text).split(), normalize(name).split()
    return sum(words[i : i + len(target)] == target for i in range(len(words) - len(target) + 1))


def pooled(clips: dict) -> dict:
    by_variety: dict[str, list[float]] = {}
    for c in clips.values():
        t = by_variety.setdefault(c["variety"], [0, 0, 0, 0])
        t[0] += c["wer"] * c["ref_words"]
        t[1] += c["ref_words"]
        t[2] += c["cer"] * c["ref_chars"]
        t[3] += c["ref_chars"]
    return {v: (t[0] / t[1], t[2] / t[3], t[1]) for v, t in by_variety.items()}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--names", help="a hotwords file; count how often each name was written correctly")
    args = parser.parse_args()
    before = json.loads((Path(args.before) / "results.json").read_text(encoding="utf-8"))
    after = json.loads((Path(args.after) / "results.json").read_text(encoding="utf-8"))

    print("| Clip | WER before | WER after | CER before | CER after |")
    print("|---|---|---|---|---|")
    for clip, b in before["clips"].items():
        a = after["clips"][clip]
        print(f"| {clip} | {b['wer']:.1%} | {a['wer']:.1%} | {b['cer']:.1%} | {a['cer']:.1%} |")
    print("\n| Variety (pooled) | Ref words | WER before | WER after | CER before | CER after |")
    print("|---|---|---|---|---|---|")
    pb, pa = pooled(before["clips"]), pooled(after["clips"])
    for variety, (wer_b, cer_b, n) in pb.items():
        wer_a, cer_a, _ = pa[variety]
        print(f"| {variety} | {n} | {wer_b:.1%} | {wer_a:.1%} | {cer_b:.1%} | {cer_a:.1%} |")

    if args.names:
        names = read_names(args.names)
        print("\n| Name | Said (reference) | Written right before | Written right after |")
        print("|---|---|---|---|")
        for name in names:
            said = right_b = right_a = 0
            for clip in before["clips"]:
                reference = (SAMPLES / f"{clip}.ref.txt").read_text(encoding="utf-8-sig")
                n_ref = count(reference, name)
                said += n_ref
                right_b += min(n_ref, count((Path(args.before) / f"{clip}.hyp.txt").read_text(encoding="utf-8"), name))
                right_a += min(n_ref, count((Path(args.after) / f"{clip}.hyp.txt").read_text(encoding="utf-8"), name))
            print(f"| {name} | {said} | {right_b} | {right_a} |")


if __name__ == "__main__":
    main()
