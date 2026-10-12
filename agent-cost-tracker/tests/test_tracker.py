import logging

import pytest

from agent_cost_tracker import BudgetExceeded, tracked_call
from agent_cost_tracker import ledger

from .conftest import FakeClient

ARGS = dict(model="claude-haiku-5-5", max_tokens=100,
            messages=[{"role": "user", "content": "hi"}])


def test_records_one_row_per_call(db):
    client = FakeClient(input_tokens=1000, output_tokens=200)
    tracked_call(client, operation="extract", run_id="run-1", **ARGS)
    tracked_call(client, operation="extract", run_id="run-1", **ARGS)

    rows = ledger.connect(db).execute("SELECT * FROM calls").fetchall()
    assert len(rows) == 2
    row = rows[0]
    assert row["operation"] == "extract"
    assert row["run_id"] == "run-1"
    assert row["model"] == "claude-haiku-5-5"
    assert row["input_tokens"] == 1000
    assert row["cache_read_tokens"] == 0  # None from the API is stored as 0
    assert row["stop_reason"] == "end_turn"
    assert row["cost_usd"] == pytest.approx(1000 * 0.10 / 1e6 + 200 * 0.50 / 1e6)


def test_budget_stops_the_call_before_it_happens(db, monkeypatch):
    monkeypatch.setenv("COST_BUDGET_USD", "0.0001")
    client = FakeClient(input_tokens=0, output_tokens=200_000)  # $0.10
    tracked_call(client, operation="extract", **ARGS)  # allowed: spend was 0

    with pytest.raises(BudgetExceeded):
        tracked_call(client, operation="extract", **ARGS)
    assert client.calls == 1  # the second call never reached the API


def test_failed_api_call_records_nothing(db):
    class BrokenClient(FakeClient):
        def create(self, **kwargs):
            raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        tracked_call(BrokenClient(), operation="extract", **ARGS)
    assert ledger.total_spend(ledger.connect(db)) == 0


def test_soft_alert_logs_but_does_not_stop(db, caplog):
    client = FakeClient(input_tokens=0, output_tokens=200_000)  # $0.10 each
    with caplog.at_level(logging.WARNING):
        tracked_call(client, operation="summarize", alert_usd=0.05, **ARGS)
    assert "summarize" in caplog.text
    assert client.calls == 1


def test_unknown_model_fails_before_the_call(db):
    client = FakeClient()
    with pytest.raises(KeyError):
        tracked_call(client, operation="extract", model="claude-haiku-5-5-20261001",
                     max_tokens=100, messages=[{"role": "user", "content": "hi"}])
    assert client.calls == 0  # nothing was sent, so nothing was billed
