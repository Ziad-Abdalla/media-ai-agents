"""Score a saved real model run. No API call, so it is free and gives the same answer every time.

If someone changes the scorer or the gold labels by accident, this test notices.
"""

import json
from pathlib import Path

import pytest

from breakdown.eval import BASELINE, GOLD, RUNS, load_jsonl, main
from breakdown.score import score_run


def test_baseline_run_scores_match_what_was_accepted():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    preds = {p["scene_number"]: p for p in load_jsonl(RUNS / f"{baseline['run_id']}.jsonl")}
    result = score_run(preds, load_jsonl(GOLD))
    for field, value in baseline["fields"].items():
        assert result["fields"][field] == pytest.approx(value)


def test_gate_passes_on_the_baseline_itself(tmp_path, monkeypatch):
    # Run the real CLI on the saved run, but write history to a temp file.
    monkeypatch.setattr("breakdown.eval.HISTORY", tmp_path / "history.csv")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert main(["--from-run", str(RUNS / f"{baseline['run_id']}.jsonl"), "--baseline"]) == 0
