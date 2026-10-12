"""Against the real Odoo in docker (run scripts/setup_odoo.py first). No AI spend:
the extraction is canned. Run with:  python -m pytest -m live"""

import uuid

import pytest

from odoo_agent.odoo_client import OdooClient
from odoo_agent.pipeline import process_email
from odoo_agent.rollback import rollback

from ..conftest import NORMAL_REQUEST, FakeAnthropic, approve, make_email

pytestmark = pytest.mark.live


class LosesAnswerOnce(OdooClient):
    """The real Odoo client, except the first create's answer is "lost" after Odoo saved it."""
    lost = False

    def create(self, model, values):
        record_id = super().create(model, values)
        if model == "purchase.order" and not self.lost:
            self.lost = True
            raise ConnectionResetError("simulated: connection dropped after create")
        return record_id


def pos_with_origin(odoo, origin):
    return odoo.search_read("purchase.order", [("origin", "=", origin)], ["id", "name", "state"])


def test_lost_answer_retry_and_rollback_on_real_odoo(store):
    odoo = LosesAnswerOnce()
    email = make_email(message_id=f"<{uuid.uuid4()}@sadaf.example>")
    run_id = process_email(email, client=FakeAnthropic(), odoo=odoo, store=store)
    origin = store.get_run(run_id)["plan_json"][-1]["values"]["origin"]

    with pytest.raises(ConnectionResetError):
        approve(store, odoo, run_id, "live-test")
    assert len(pos_with_origin(odoo, origin)) == 1  # Odoo did create it

    po_id = approve(store, odoo, run_id, "live-test")  # retry
    found = pos_with_origin(odoo, origin)
    assert [p["id"] for p in found] == [po_id]  # still exactly one
    assert found[0]["state"] == "draft"

    rollback(store, odoo, run_id, actor="human:live-test")
    assert pos_with_origin(odoo, origin) == []


def test_new_vendor_then_rollback_on_real_odoo(store):
    odoo = OdooClient()
    vendor = f"{uuid.uuid4().hex} Trading"  # random, so it never looks like an earlier test vendor
    email = make_email(message_id=f"<{uuid.uuid4()}@sadaf.example>")
    run_id = process_email(email, client=FakeAnthropic({**NORMAL_REQUEST, "vendor_name": vendor}),
                           odoo=odoo, store=store)
    assert store.get_run(run_id)["status"] == "pending_approval"
    approve(store, odoo, run_id, "live-test")
    partner = odoo.search_read("res.partner", [("name", "=", vendor)], ["id"])
    assert len(partner) == 1

    rollback(store, odoo, run_id, actor="human:live-test")
    assert odoo.search_read("res.partner", [("name", "=", vendor)], ["id"]) == []  # archived
    origin = store.get_run(run_id)["plan_json"][-1]["values"]["origin"]
    assert pos_with_origin(odoo, origin) == []


def test_po_line_is_charged_to_the_production_on_real_odoo(store):
    """Odoo 17 stores analytic_distribution as JSON; check it lands and the budget sees it."""
    from odoo_agent import budget

    odoo = OdooClient()
    run_id = process_email(make_email(message_id=f"<{uuid.uuid4()}@sadaf.example>"),
                           client=FakeAnthropic({**NORMAL_REQUEST, "approval_reference": f"APR-{uuid.uuid4().hex[:6]}"}),
                           odoo=odoo, store=store)
    production = store.get_run(run_id)["resolution_json"]["production"]
    assert production["code"] == "RML-S1"
    before, _ = budget.committed_sar(odoo, production["analytic_id"])

    po_id = approve(store, odoo, run_id, "live-test")
    [line] = odoo.search_read("purchase.order.line", [("order_id", "=", po_id)], ["analytic_distribution"])
    assert line["analytic_distribution"] == {str(production["analytic_id"]): 100.0}
    assert budget.committed_sar(odoo, production["analytic_id"])[0] == before + 7000

    rollback(store, odoo, run_id, actor="human:live-test")
    assert budget.committed_sar(odoo, production["analytic_id"])[0] == before
