"""Run the agent on the test script, score it against the gold labels, and gate releases.

    python -m breakdown.eval --model claude-haiku-5-5 --effort low
    python -m breakdown.eval --model claude-haiku-5-5 --effort low --gate   # the release gate
    python -m breakdown.eval --from-run eval/runs/<run>.jsonl              # re-score, no API cost
    python -m breakdown.eval ... --accept                                  # make this run the new baseline
    python -m breakdown.eval ... --no-cast-list                            # the README experiment

Every run (live, or a re-score with a new scorer version) appends one row to eval/history.csv,
so you can see the score of every model / prompt version over time, next to what it cost.
Re-scoring the same run with the same scorer again does not add a duplicate row.

The hard set is a separate, small set of harder scenes with its own gold, baseline, history and gate:

    python -m breakdown.eval --set hard --model claude-haiku-5-5 --effort low --gate
    python -m breakdown.eval --set hard --from-run eval/runs/hard-<run>.jsonl --gate

Its gate is stricter: on top of the per-field threshold, each hard scene has zero-tolerance checks
(for example "the Ferrari the injected text asks for must not appear"), and one broken check fails the gate.
"""

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_cost_tracker import ledger

from .cast_aliases import HARD_SET, KAMERA_JADDI, CastNames
from .extract import DEFAULT_MODEL, PROMPT_VERSION
from .pipeline import breakdown_script, make_client
from .report import write_jsonl
from .score import ALL_FIELDS, SCORER_VERSION, critical_failures, regression_check, scene_errors, score_run

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
GOLD = EVAL_DIR / "gold.jsonl"
HISTORY = EVAL_DIR / "history.csv"
BASELINE = EVAL_DIR / "baseline.json"
RUNS = EVAL_DIR / "runs"
SCRIPT = ROOT / "data" / "kamera_jaddi.txt"
HARD_DIR = EVAL_DIR / "hard"
HARD_SCRIPT = ROOT / "data" / "hard_scenes.txt"
DEFAULT_THRESHOLD = 0.05  # a field may not drop more than 5 points vs the accepted baseline

HISTORY_COLUMNS = ["date", "commit", "model", "effort", "prompt_version", "scorer_version", "source",
                   *ALL_FIELDS, "overall", "cost_usd", "failed_scenes", "run_id"]
HARD_HISTORY_COLUMNS = HISTORY_COLUMNS + ["critical_failures"]


@dataclass
class EvalSet:
    """One test set: its script, correct answers, accepted baseline, history file and cast names."""
    name: str
    script: Path
    gold: Path
    baseline: Path
    history: Path
    history_columns: list[str]
    names: CastNames
    run_prefix: str  # saved runs of the hard set start with "hard-"


def get_eval_set(name: str) -> EvalSet:
    # Built when called, not at import, so tests can point HISTORY / HARD_DIR at temp files.
    if name == "hard":
        return EvalSet("hard", HARD_SCRIPT, HARD_DIR / "gold.jsonl", HARD_DIR / "baseline.json",
                       HARD_DIR / "history.csv", HARD_HISTORY_COLUMNS, HARD_SET, "hard-")
    return EvalSet("main", SCRIPT, GOLD, BASELINE, HISTORY, HISTORY_COLUMNS, KAMERA_JADDI, "")


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
    conn = ledger.connect()
    try:
        return ledger.run_spend(conn, run_id)
    finally:
        conn.close()


def print_report(result: dict, preds: dict, golds: list[dict], names: CastNames = KAMERA_JADDI) -> list[str]:
    """Print the scores and the errors per scene. Returns the hard-case checks that broke (if any)."""
    print("\nField          Score   (precision / recall)")
    for field, value in result["fields"].items():
        extra = ""
        if field in result["detail"]:
            d = result["detail"][field]
            extra = f"   ({d['precision']:.2f} / {d['recall']:.2f})"
        print(f"{field:<14} {value:.3f}{extra}")
    print(f"{'OVERALL':<14} {result['overall']:.3f}\n")
    print("Errors per scene:")
    broken_all = []
    for scored, gold in zip(result["scenes"], golds):
        pred = preds.get(gold["scene_number"])
        errs = scene_errors(scored, pred, gold)
        broken = critical_failures(scored, pred, gold, names)
        broken_all += [f"scene {gold['scene_number']}: {b}" for b in broken]
        if errs or broken:
            print(f"  scene {gold['scene_number']}:")
            for e in errs:
                print(f"    - {e}")
            for b in broken:
                print(f"    - HARD CHECK FAILED: {b}")
    return broken_all


def append_history(row: dict, history: Path, columns: list[str]) -> None:
    new = not history.exists()
    if not new:
        with open(history, encoding="utf-8", newline="") as f:
            for old in csv.DictReader(f):
                if (old["run_id"], old["scorer_version"]) == (row["run_id"], row["scorer_version"]):
                    return  # this run was already scored with this scorer
    history.parent.mkdir(parents=True, exist_ok=True)
    with open(history, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if new:
            writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate the script-breakdown agent")
    parser.add_argument("--set", dest="eval_set", choices=["main", "hard"], default="main",
                        help="main = the 26-scene episode; hard = the separate hard-case scenes")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", choices=["low", "medium", "high"], default=None)
    parser.add_argument("--from-run", type=Path, help="score a saved run instead of calling the API")
    parser.add_argument("--gate", action="store_true",
                        help="fail if any field drops vs the baseline, if any scene failed, "
                             "or (hard set) if any hard-case check broke")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--accept", action="store_true", help="save this run as the new baseline")
    parser.add_argument("--no-cast-list", action="store_true",
                        help="experiment: send an empty cast list to the model")
    args = parser.parse_args(argv)

    es = get_eval_set(args.eval_set)
    golds = load_jsonl(es.gold)

    if args.from_run:
        # Re-score a saved run: no API call, no cost. Used after changing the scorer or the gold labels.
        preds = {p["scene_number"]: p for p in load_jsonl(args.from_run)}
        run_id = args.from_run.stem
        meta_path = args.from_run.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        made_on = meta.get("set", "main")
        if made_on != es.name:
            print(f"This run was made on the {made_on} set. Add --set {made_on}.")
            return 2
        source = "rescored"
    else:
        client = make_client()
        run_id = f"{es.run_prefix}{args.model}-{args.effort or 'default'}-{datetime.now():%Y%m%d-%H%M%S}"
        prompt_version = PROMPT_VERSION + ("-no-cast-list" if args.no_cast_list else "")
        scenes, errors = breakdown_script(es.script.read_text(encoding="utf-8"), client,
                                          model=args.model, effort=args.effort, run_id=run_id,
                                          use_cast_list=not args.no_cast_list, names=es.names)
        RUNS.mkdir(exist_ok=True)
        write_jsonl(scenes, RUNS / f"{run_id}.jsonl")
        preds = {s.scene_number: s.model_dump() for s in scenes}
        meta = {"model": args.model, "effort": args.effort or "default", "prompt_version": prompt_version,
                "commit": git_commit(), "date": datetime.now().isoformat(timespec="minutes"),
                "cost_usd": run_cost(run_id), "failed_scenes": len(errors)}
        if es.name != "main":
            meta["set"] = es.name  # main-set runs keep the old meta format
        (RUNS / f"{run_id}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        source = "live"
        for e in errors:
            print("FAILED", e)

    result = score_run(preds, golds, es.names)
    model, effort = meta.get("model", "?"), meta.get("effort", "?")
    print(f"Run {run_id}  set={es.name}  model={model}  effort={effort}"
          f"  prompt={meta.get('prompt_version', '?')}  scorer={SCORER_VERSION}")
    broken = print_report(result, preds, golds, es.names)
    if any("critical" in g for g in golds):
        print(f"Hard-case checks broken: {len(broken)}")
    cost = meta.get("cost_usd")
    if cost is not None:
        print(f"Cost of this run: ${cost:.4f}")
    row = {
        "date": meta.get("date", ""), "commit": meta.get("commit", ""), "model": model, "effort": effort,
        "prompt_version": meta.get("prompt_version", ""), "scorer_version": SCORER_VERSION, "source": source,
        **{f: f"{v:.3f}" for f, v in result["fields"].items()},
        "overall": f"{result['overall']:.3f}", "cost_usd": "" if cost is None else f"{cost:.4f}",
        "failed_scenes": meta.get("failed_scenes", ""), "run_id": run_id,
    }
    if "critical_failures" in es.history_columns:
        row["critical_failures"] = len(broken)
    append_history(row, es.history, es.history_columns)

    status = 0
    if args.gate:
        if not es.baseline.exists():
            print("No baseline yet. Run once with --accept to create one.")
            status = 1
        else:
            base = json.loads(es.baseline.read_text(encoding="utf-8"))
            failures = regression_check(result["fields"], base["fields"], args.threshold)
            # A missing scene costs only about 0.04 on 26 scenes, under the threshold,
            # so the average alone would let it through. Any failed or missing scene fails the gate.
            missing = [g["scene_number"] for g in golds if g["scene_number"] not in preds]
            if missing:
                failures.append(f"scenes with no answer: {missing}")
            if meta.get("failed_scenes"):
                failures.append(f"{meta['failed_scenes']} scene(s) failed during the run")
            # Hard-case checks have zero tolerance: one broken check fails the gate on its own.
            failures += [f"hard check: {b}" for b in broken]
            if failures:
                print(f"GATE FAILED vs baseline {base['run_id']} (threshold {args.threshold}):")
                for f in failures:
                    print("  -", f)
                status = 1
            else:
                print(f"GATE PASSED vs baseline {base['run_id']}")

    if args.accept and status == 0:
        es.baseline.parent.mkdir(parents=True, exist_ok=True)
        es.baseline.write_text(json.dumps({
            "run_id": run_id, "model": model, "effort": effort, "prompt_version": meta.get("prompt_version"),
            "scorer_version": SCORER_VERSION, "fields": result["fields"], "overall": result["overall"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved as the new baseline: {es.baseline.name} ({es.name} set)")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
