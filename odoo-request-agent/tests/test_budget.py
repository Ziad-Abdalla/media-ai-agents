"""Per-production budget check: warns on the page, and over budget needs a written reason."""

import re

import pytest
from fastapi.testclient import TestClient

from odoo_agent import budget
from odoo_agent.pipeline import approve_run, process_email
from odoo_agent.plan import plan_hash
from odoo_agent.web import create_app

from .conftest import NORMAL_REQUEST, FakeAnthropic, approve, make_email
from .test_pipeline import run

# The talk show (SHK-S3) has a 60,000 SAR budget in production_budgets.json.
TALK_SHOW = {**NORMAL_REQUEST, "production": "Sahrat Al-Khamis",
             "items": [{"name": "LED wall rental", "quantity": 3, "unit_price": 4500, "currency": "SAR",
                        "category": "equipment_rental"}]}  # 13,500 SAR


def production(odoo, code):
    return {"analytic_id": odoo.production_ids[code], "name": code, "code": code}


def test_committed_counts_open_pos_by_their_share(odoo):
    odoo.commit_spend("SHK-S3", 40_000)
    cancelled = odoo.commit_spend("SHK-S3", 9_999)
    odoo.records["purchase.order"][cancelled]["state"] = "cancel"
    odoo.commit_spend("RML-S1", 5_000)  # another production
    assert budget.committed_sar(odoo, odoo.production_ids["SHK-S3"]) == (40_000, 1)


@pytest.mark.parametrize("earlier, status", [(10_000, "ok"), (41_000, "near"), (50_000, "over")])
def test_budget_states(odoo, earlier, status):
    odoo.commit_spend("SHK-S3", earlier)
    result = budget.check(odoo, production(odoo, "SHK-S3"), 13_500)
    assert result["status"] == status
    assert result["after"] == earlier + 13_500


def test_usd_is_converted_at_the_peg(odoo):
    from odoo_agent.models import PurchaseRequest
    request = PurchaseRequest.model_validate(
        {**NORMAL_REQUEST, "items": [{**NORMAL_REQUEST["items"][0], "quantity": 1, "unit_price": 100,
                                      "currency": "USD"}]})
    assert budget.order_total_sar(request) == 375


def test_over_budget_without_a_reason_is_refused(store, odoo):
    odoo.commit_spend("SHK-S3", 50_000)
    r = run(store, odoo, client=FakeAnthropic(TALK_SHOW))
    assert r["status"] == "pending_approval"  # a warning, not a block: a person decides
    with pytest.raises(ValueError, match="over-budget"):
        approve(store, odoo, r["run_id"])
    assert len(odoo.pos()) == 1  # only the earlier PO
    assert store.get_run(r["run_id"])["status"] == "pending_approval"
    assert store.audit_rows(r["run_id"])[-1]["operation"] == "refused: over budget without a reason"


def test_over_budget_with_a_reason_writes_and_is_audited(store, odoo):
    odoo.commit_spend("SHK-S3", 50_000)
    r = run(store, odoo, client=FakeAnthropic(TALK_SHOW))
    shown = plan_hash(r["plan_json"])
    approve_run(store, odoo, r["run_id"], "Ziad", shown, over_budget_reason="opening episode, CFO ok")
    assert len(odoo.pos()) == 2
    row = [a for a in store.audit_rows(r["run_id"]) if a["operation"] == "approve_over_budget"][0]
    assert row["after"]["reason"] == "opening episode, CFO ok" and row["after"]["status"] == "over"


def test_a_retry_does_not_count_its_own_po_twice(store, odoo):
    odoo.commit_spend("SHK-S3", 40_000)  # 40,000 + 13,500 = 89%: within budget
    r = run(store, odoo, client=FakeAnthropic(TALK_SHOW))
    odoo.lose_next_create_answer = True
    with pytest.raises(ConnectionResetError):
        approve(store, odoo, r["run_id"])
    # The PO exists now. Counting it again would make 67,000 = over budget and block the retry.
    assert budget.check_run(odoo, store.get_run(r["run_id"]))["status"] == "ok"
    approve(store, odoo, r["run_id"])
    assert store.get_run(r["run_id"])["status"] == "done"


def test_page_warns_and_asks_for_a_tick_and_a_reason(store, odoo):
    odoo.commit_spend("SHK-S3", 50_000)
    run_id = process_email(make_email(), client=FakeAnthropic(TALK_SHOW), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))
    page = web.get(f"/?run={run_id}").text
    assert "Over budget." in page and "105.8%" in page
    assert 'name="over_budget_ok"' in page and 'name="over_budget_reason"' in page

    shown = re.search(r'name="plan_hash" value="([0-9a-f]{64})"', page).group(1)
    # A reason without the tick doesn't count.
    web.post(f"/runs/{run_id}/approve", data={"approver": "Ziad", "plan_hash": shown,
                                              "over_budget_reason": "because"})
    assert len(odoo.pos()) == 1
    web.post(f"/runs/{run_id}/approve", data={"approver": "Ziad", "plan_hash": shown,
                                              "over_budget_ok": "yes", "over_budget_reason": "because"})
    assert len(odoo.pos()) == 2


def test_page_still_loads_when_odoo_is_down(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)

    def odoo_down():
        raise ConnectionRefusedError("no Odoo")
    page = TestClient(create_app(store, odoo_down)).get("/").text
    assert run_id in page and "Budget check unavailable" in page
