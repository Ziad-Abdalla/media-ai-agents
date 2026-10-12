"""The KPI report: numbers computed from the runs, the audit log and the cost ledger."""

from fastapi.testclient import TestClient

from odoo_agent import config, kpis
from odoo_agent.pipeline import reject_run, resolve_needs_human
from odoo_agent.rollback import rollback
from odoo_agent.web import create_app

from .conftest import NORMAL_REQUEST, FakeAnthropic, approve
from .test_pipeline import run


def order(n):
    """A different order each time, so runs are not flagged as re-sends of each other."""
    return {**NORMAL_REQUEST, "approval_reference": f"APR-2026-{n:04d}"}


def demo_runs(store, odoo):
    auto = run(store, odoo, client=FakeAnthropic(order(1)), message_id="<1@sadaf.example>")
    approve(store, odoo, auto["run_id"])                                        # done, auto

    unsure = run(store, odoo, client=FakeAnthropic({**order(2), "production": "رمال"}),
                 message_id="<2@sadaf.example>")
    resolve_needs_human(store, unsure["run_id"], production_id=odoo.production_ids["RML-S1"])
    approve(store, odoo, unsure["run_id"])                                      # done, needed a human

    undone = run(store, odoo, client=FakeAnthropic(order(3)), message_id="<3@sadaf.example>")
    approve(store, odoo, undone["run_id"])
    rollback(store, odoo, undone["run_id"])                                     # rolled back

    rejected = run(store, odoo, client=FakeAnthropic(order(4)), message_id="<4@sadaf.example>")
    reject_run(store, rejected["run_id"], "Ziad")                               # rejected

    run(store, odoo, client=FakeAnthropic({**order(5), "approval_reference": None}),
        message_id="<5@sadaf.example>")                                         # needs_info
    run(store, odoo, sender="someone@gmail.com", message_id="<6@sadaf.example>")  # blocked


def test_kpis_from_a_small_demo(store, odoo):
    demo_runs(store, odoo)
    k = kpis.compute(store)
    assert k["runs_total"] == 6
    assert (k["auto_resolved"], k["needed_human"]) == (3, 1)
    assert k["auto_resolved_pct"] == 75.0
    assert (k["needed_info"], k["blocked_senders"]) == (1, 1)
    assert (k["approved"], k["rejected"]) == (3, 1)
    assert k["approval_rate_pct"] == 75.0
    assert (k["succeeded"], k["failed_or_undone"]) == (2, 1)  # 2 done; 1 rolled back
    assert k["success_rate_pct"] == 66.7
    assert k["pos_timed"] == 3  # rolled-back PO was still created, so it is timed
    assert k["minutes_saved_estimate"] == 2 * (config.MINUTES_MANUAL_PO - config.MINUTES_REVIEW_PO)
    assert k["requests_read_by_model"] == 5  # the blocked email never reached the model
    assert k["cost_per_request_usd"] > 0
    assert list(k["draft_po_sar_by_production"].values()) == [14_000]  # two 7,000 SAR POs


def test_handling_time_is_measured_from_the_email_date(store, odoo):
    r = run(store, odoo)  # the email's Date is 2026-10-12 10:00 +03:00 (conftest.RECEIVED)
    approve(store, odoo, r["run_id"])
    k = kpis.compute(store)
    assert k["median_minutes_email_to_po"] > 0  # tests run later than that date, so it's positive


def test_an_empty_store_reports_nothing_instead_of_crashing(store):
    k = kpis.compute(store)
    assert k["runs_total"] == 0 and k["approval_rate_pct"] is None
    assert "n/a" in kpis.as_text(k)


def test_kpi_page_shows_the_numbers_and_budgets(store, odoo):
    demo_runs(store, odoo)
    page = TestClient(create_app(store, lambda: odoo)).get("/kpis").text
    assert "Approval rate" in page and "75.0%" in page
    assert "Rimal Al-Khobar" in page and "within budget" in page
    assert "synthetic" in page


def test_parse_time_reads_iso_and_email_dates():
    assert kpis.parse_time("2026-10-12T10:00:00+03:00").hour == 10
    assert kpis.parse_time("Mon, 12 Oct 2026 10:00:00 +0300").hour == 10
    assert kpis.parse_time("not a date") is None
