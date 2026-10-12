"""Run the agent on the test script, score it against the gold labels, and gate releases.

    python -m breakdown.eval --model claude-haiku-5-5 --effort low
    python -m breakdown.eval --model claude-haiku-5-5 --effort low --baseline   # the release gate
    python -m breakdown.eval --from-run eval/runs/<run>.jsonl                  # re-score, no API cost
    python -m breakdown.eval ... --accept                                      # make this run the new baseline

Every live run appends one row to eval/history.csv, so you can see the score of every
model / prompt version over time, next to what it cost.
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .extract import DEFAULT_MODEL, PROMPT_VERSION
from .report import write_jsonl
from .score import ALL_FIELDS, regression_check, scene_errors, score_run

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
GOLD = EVAL_DIR / "gold.jsonl"
HISTORY = EVAL_DIR / "history.csv"
BASELINE = EVAL_DIR / "baseline.json"
RUNS = EVAL_DIR / "runs"
SCRIPT = ROOT / "data" / "kamera_jaddi.txt"
DEFAULT_THRESHOLD = 0.05  # a field may not drop more than 5 points vs the accepted baseline

HISTORY_COLUMNS = ["date", "commit", "model", "effort", "prompt_version", *ALL_FIELDS,
                   "overall", "cost_usd", "failed_scenes", "run_id"]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "breakdown"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def run_cost(run_id: str) -> float:
    """Ask the shared cost ledger what this run cost."""
    from agent_cost_tracker import ledger
    conn = ledger.connect()
    try:
        return ledger.run_spend(conn, run_id)
    finally:
        conn.close()


def print_report(result: dict, preds: dict, golds: list[dict]) -> None:
    print("\nField          Score   (precision / recall)")
    for field, value in result["fields"].items():
        extra = ""
        if field in result["detail"]:
            d = result["detail"][field]
            extra = f"   ({d['precision']:.2f} / {d['recall']:.2f})"
        print(f"{field:<14} {value:.3f}{extra}")
    print(f"{'OVERALL':<14} {result['overall']:.3f}\n")
    print("Errors per scene:")
    for scored, gold in zip(result["scenes"], golds):
        errs = scene_errors(scored, preds.get(gold["scene_number"]), gold)
        if errs:
            print(f"  scene {gold['scene_number']}:")
            for e in errs:
                print(f"    - {e}")


def append_history(row: dict) -> None:
    new = not HISTORY.exists()
    with open(HISTORY, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate the script-breakdown agent")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", choices=["low", "medium", "high"], default=None)
    parser.add_argument("--from-run", type=Path, help="score a saved run instead of calling the API")
    parser.add_argument("--baseline", action="store_true", help="fail if any field drops vs the baseline")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--accept", action="store_true", help="save this run as the new baseline")
    args = parser.parse_args(argv)

    golds = load_jsonl(GOLD)

    if args.from_run:
        preds = {p["scene_number"]: p for p in load_jsonl(args.from_run)}
        run_id, cost, failed = args.from_run.stem, None, 0
    else:
        from .pipeline import breakdown_script, make_client
        client = make_client()
        run_id = f"{args.model}-{args.effort or 'default'}-{datetime.now():%Y%m%d-%H%M%S}"
        scenes, errors = breakdown_script(SCRIPT.read_text(encoding="utf-8"), client,
                                          model=args.model, effort=args.effort, run_id=run_id)
        RUNS.mkdir(exist_ok=True)
        write_jsonl(scenes, RUNS / f"{run_id}.jsonl")
        preds = {s.scene_number: s.model_dump() for s in scenes}
        cost, failed = run_cost(run_id), len(errors)
        for e in errors:
            print("FAILED", e)

    result = score_run(preds, golds)
    print(f"Run {run_id}  model={args.model}  effort={args.effort or 'default'}  prompt={PROMPT_VERSION}")
    print_report(result, preds, golds)
    if cost is not None:
        print(f"Cost of this run: ${cost:.4f}")
        append_history({
            "date": datetime.now().isoformat(timespec="minutes"), "commit": git_commit(),
            "model": args.model, "effort": args.effort or "default", "prompt_version": PROMPT_VERSION,
            **{f: f"{v:.3f}" for f, v in result["fields"].items()},
            "overall": f"{result['overall']:.3f}", "cost_usd": f"{cost:.4f}",
            "failed_scenes": failed, "run_id": run_id,
        })

    status = 0
    if args.baseline:
        if not BASELINE.exists():
            print("No baseline yet. Run once with --accept to create one.")
            status = 1
        else:
            base = json.loads(BASELINE.read_text(encoding="utf-8"))
            failures = regression_check(result["fields"], base["fields"], args.threshold)
            if failures:
                print(f"GATE FAILED vs baseline {base['run_id']} (threshold {args.threshold}):")
                for f in failures:
                    print("  -", f)
                status = 1
            else:
                print(f"GATE PASSED vs baseline {base['run_id']}")

    if args.accept and status == 0:
        BASELINE.write_text(json.dumps({
            "run_id": run_id, "model": args.model, "effort": args.effort or "default",
            "prompt_version": PROMPT_VERSION, "fields": result["fields"], "overall": result["overall"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved as the new baseline: {BASELINE.name}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
