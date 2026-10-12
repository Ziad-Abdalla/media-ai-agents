from agent_cost_tracker import ledger, tracked_call
from agent_cost_tracker.report import build_report

from .conftest import FakeClient

ARGS = dict(model="claude-haiku-5-5", max_tokens=100,
            messages=[{"role": "user", "content": "hi"}])


def test_report_groups_by_operation_and_run(db):
    client = FakeClient(input_tokens=0, output_tokens=200_000)  # $0.10 per call
    tracked_call(client, operation="extract", run_id="a", **ARGS)
    tracked_call(client, operation="extract", run_id="b", **ARGS)
    tracked_call(client, operation="draft_reply", run_id="b", **ARGS)

    text = build_report(ledger.connect(db))
    assert "extract" in text and "draft_reply" in text
    assert "2 runs, mean $0.15000, max $0.20000" in text
    assert "Total: $0.30000 of $15.00 budget (2.00% used)" in text


def test_report_on_empty_ledger(db):
    assert "(no calls yet)" in build_report(ledger.connect(db))


def test_report_for_one_operation(db):
    client = FakeClient(input_tokens=0, output_tokens=200_000)  # $0.10 per call
    tracked_call(client, operation="extract", run_id="a", **ARGS)
    tracked_call(client, operation="draft_reply", run_id="a", **ARGS)
    tracked_call(client, operation="draft_reply", run_id="b", **ARGS)

    text = build_report(ledger.connect(db), operation="extract")
    assert "draft_reply" not in text
    assert "1 runs, mean $0.10000, max $0.10000" in text
    assert "Total for extract: $0.10000" in text


def test_report_with_zero_budget_does_not_crash(db, monkeypatch):
    monkeypatch.setenv("COST_BUDGET_USD", "0")
    assert "budget is $0" in build_report(ledger.connect(db))
