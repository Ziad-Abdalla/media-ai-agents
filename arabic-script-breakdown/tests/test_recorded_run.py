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
    assert main(["--from-run", str(RUNS / f"{baseline['run_id']}.jsonl"), "--gate"]) == 0


def _copy_baseline_run(tmp_path, drop_scene=None, failed_scenes=0):
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    rows = [r for r in load_jsonl(RUNS / f"{baseline['run_id']}.jsonl") if r["scene_number"] != drop_scene]
    run = tmp_path / "run.jsonl"
    run.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "run.meta.json").write_text(json.dumps({"failed_scenes": failed_scenes}), encoding="utf-8")
    return run


def test_gate_fails_when_one_scene_is_missing(tmp_path, monkeypatch, capsys):
    # One missing scene drops each field by less than the 0.05 threshold,
    # so this checks the separate "no scene may be missing" rule.
    monkeypatch.setattr("breakdown.eval.HISTORY", tmp_path / "history.csv")
    assert main(["--from-run", str(_copy_baseline_run(tmp_path, drop_scene=9)), "--gate"]) == 1
    assert "scenes with no answer: [9]" in capsys.readouterr().out


def test_gate_fails_when_a_scene_failed_during_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr("breakdown.eval.HISTORY", tmp_path / "history.csv")
    assert main(["--from-run", str(_copy_baseline_run(tmp_path, failed_scenes=1)), "--gate"]) == 1


def test_rescoring_the_same_run_twice_logs_one_row(tmp_path, monkeypatch):
    history = tmp_path / "history.csv"
    monkeypatch.setattr("breakdown.eval.HISTORY", history)
    run = _copy_baseline_run(tmp_path)
    main(["--from-run", str(run)])
    main(["--from-run", str(run)])
    assert len(history.read_text(encoding="utf-8").splitlines()) == 2  # header + one row
