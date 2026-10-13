"""Run the pipeline on every clip in data/samples/ and score it.

    python scripts/fetch_samples.py      # once
    python scripts/run_eval.py --model large-v3-turbo

Writes one .srt per clip and a results table to results/<model>-<device>/.
Needs the package installed first (pip install -e .).

To measure hotwords, run it again with a hotwords file and a tag, then compare:

    python scripts/run_eval.py --hotwords-file data/hotwords/aldeerah_net_cast.txt --tag cast
    python scripts/compare_runs.py results/large-v3-turbo-cuda results/large-v3-turbo-cuda-cast
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from gulf_srt.evaluate import normalize, score
from gulf_srt.segment import build_cues
from gulf_srt.srt import write_srt
from gulf_srt.transcribe import load_model, transcribe
from gulf_srt.transcript import read_hotwords, save_transcript

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--hotwords-file", action="append", default=[],
                        help="one name or phrase per line, passed to Whisper as hotwords (can be repeated)")
    parser.add_argument("--tag", help="added to the results folder name, e.g. 'cast' -> large-v3-turbo-cuda-cast")
    args = parser.parse_args()
    hotwords = [name for f in args.hotwords_file for name in read_hotwords(file=f)]

    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    model, device = load_model(args.model, args.device)
    folder = f"{args.model}-{device}" + (f"-{args.tag}" if args.tag else "")  # the device that really ran
    out_dir = ROOT / "results" / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    transcribe(model, np.zeros(16000, dtype=np.float32))  # warm-up, so clip 1 isn't charged for start-up

    header = (
        "| Clip | Variety | Length (s) | WER light | WER Arabic-norm | CER Arabic-norm | RTF |\n"
        "|---|---|---|---|---|---|---|"
    )
    rows, scores = [], {}
    totals: dict[str, list[float]] = {}  # variety -> [word errors, ref words, char errors, ref chars]
    for clip in manifest:
        started = time.perf_counter()
        transcript = transcribe(model, str(SAMPLES / f"{clip['id']}.wav"), hotwords=hotwords)
        cues = build_cues(transcript.words)
        elapsed = time.perf_counter() - started
        duration = transcript.duration
        write_srt(cues, out_dir / f"{clip['id']}.srt")
        save_transcript(transcript, out_dir / f"{clip['id']}.words.json")
        hypothesis = " ".join(w.text for w in transcript.words)
        (out_dir / f"{clip['id']}.hyp.txt").write_text(hypothesis, encoding="utf-8")

        wer_light = wer_norm = cer_norm = "n/a (no reference)"
        ref_path = SAMPLES / f"{clip['id']}.ref.txt"
        if ref_path.exists():  # also picks up references you add later (data/needs_reference.md)
            reference = ref_path.read_text(encoding="utf-8-sig")  # -sig: ignore a BOM from Windows editors
            light, arabic_norm = score(reference, hypothesis, arabic=False), score(reference, hypothesis)
            wer_light = f"{light['wer']:.1%}"
            wer_norm, cer_norm = f"{arabic_norm['wer']:.1%}", f"{arabic_norm['cer']:.1%}"
            n_words, n_chars = len(normalize(reference).split()), len(normalize(reference))
            t = totals.setdefault(clip["variety"], [0, 0, 0, 0])
            t[0] += arabic_norm["wer"] * n_words
            t[1] += n_words
            t[2] += arabic_norm["cer"] * n_chars
            t[3] += n_chars
            scores[clip["id"]] = {"variety": clip["variety"], "ref_words": n_words, "ref_chars": n_chars,
                                  "wer": arabic_norm["wer"], "cer": arabic_norm["cer"], "wer_light": light["wer"]}
        rtf = elapsed / duration
        rows.append(
            f"| {clip['id']} | {clip['variety']} | {duration:.1f} | {wer_light} | {wer_norm} | {cer_norm} | {rtf:.3f} |"
        )
        print(rows[-1])

    pooled = ["", "| Variety (pooled) | Ref words | WER Arabic-norm | CER Arabic-norm |", "|---|---|---|---|"]
    for variety, (word_errors, n_words, char_errors, n_chars) in totals.items():
        pooled.append(f"| {variety} | {n_words} | {word_errors / n_words:.1%} | {char_errors / n_chars:.1%} |")
    print("\n".join(pooled))
    table = "\n".join([f"Model `{args.model}` on `{device}`.\n", header, *rows, *pooled]) + "\n"
    (out_dir / "results.md").write_text(table, encoding="utf-8")
    summary = {"model": args.model, "device": device, "hotwords": hotwords, "clips": scores}
    (out_dir / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten to {out_dir}")


if __name__ == "__main__":
    main()
