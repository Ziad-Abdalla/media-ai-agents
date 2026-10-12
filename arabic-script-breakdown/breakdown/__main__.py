"""Run the agent on a script and write the production files.

    python -m breakdown data/kamera_jaddi.txt --out output
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .extract import DEFAULT_MODEL
from .pipeline import breakdown_script, make_client
from .report import write_csv, write_jsonl, write_schedule


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Arabic script breakdown")
    parser.add_argument("script", type=Path)
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", choices=["low", "medium", "high"], default=None)
    args = parser.parse_args()

    client = make_client()
    run_id = f"run-{datetime.now():%Y%m%d-%H%M%S}"
    scenes, errors = breakdown_script(args.script.read_text(encoding="utf-8"), client,
                                      model=args.model, effort=args.effort, run_id=run_id)
    args.out.mkdir(parents=True, exist_ok=True)
    write_jsonl(scenes, args.out / "breakdown.jsonl")
    write_csv(scenes, args.out / "production_sheet.csv")
    write_schedule(scenes, args.out / "schedule.md")
    print(f"{len(scenes)} scenes written to {args.out}/ (run {run_id})")
    for e in errors:
        print("FAILED", e)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
