"""The whole flow with a fake model and a fake Odoo: statuses, duplicates, idempotency."""

import threading
import time

import pytest

from odoo_agent.pipeline import approve_run, process_email, resolve_needs_human
from odoo_agent.plan import plan_hash

from .conftest import NORMAL_REQUEST, FakeAnthropic, approve, make_email


def run(store, odoo, client=None, **email_kwargs):
    client = client or FakeAnthropic()
    run_id = process_email(make_email(**email_kwargs), client=client, odoo=odoo, store=store)
    return store.get_run(run_id) if run_id else None


def test_normal_request_waits_for_approval_and_writes_nothing(store, odoo):
    r = run(store, odoo)
    assert r["status"] == "pending_approval"
    assert odoo.pos() == []  # nothing written before a human says yes
    [step] = r["plan_json"]
    assert step["action"] == "create_purchase_order"
    values = step["values"]
    assert values["partner_ref"] == "APR-2026-0412"
    assert values["origin"] == "email-agent:" + r["idempotency_key"]
    line = values["order_line"][0][2]
    assert (line["product_qty"], line["price_unit"]) == (2, 3500)


def test_approval_creates_one_draft_po(store, odoo):
    r = run(store, odoo)
    po_id = approve(store, odoo, r["run_id"], "Ziad")
    [po] = odoo.pos()
    assert po["id"] == po_id and po["state"] == "draft"
    assert store.get_run(r["run_id"])["status"] == "done"


def test_missing_fields_ask_for_info_and_draft_a_reply(store, odoo):
    incomplete = {**NORMAL_REQUEST, "approval_reference": None,
                  "items": [{"name": "Lighting kit", "quantity": None, "unit_price": None,
                             "currency": None, "category": "equipment_rental"}]}
    r = run(store, odoo, client=FakeAnthropic(incomplete))
    assert r["status"] == "needs_info"
    assert "approval reference" in r["reply_draft"]
    assert r["plan_json"] is None


def test_outside_sender_is_ignored_without_spending_money(store, odoo):
    client = FakeAnthropic()
    r = run(store, odoo, client=client, sender="ceo@sadaf-example.com")
    assert r["status"] == "blocked_sender"
    assert client.sent == []  # the model was never called


def test_same_email_twice_is_processed_once(store, odoo):
    client = FakeAnthropic()
    run(store, odoo, client=client)
    assert run(store, odoo, client=client) is None
    assert len(client.sent) == 1


def test_resent_request_is_flagged_as_duplicate(store, odoo):
    first = run(store, odoo, message_id="<a@sadaf.example>")
    second = run(store, odoo, message_id="<b@sadaf.example>")
    assert second["status"] == "needs_human"
    assert second["duplicate_of"] == first["run_id"]


def test_unknown_vendor_needs_approval_to_be_created(store, odoo):
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "vendor_name": "Najd Catering House"}))
    assert [s["action"] for s in r["plan_json"]] == ["create_vendor", "create_purchase_order"]
    assert r["status"] == "pending_approval"
    approve(store, odoo, r["run_id"], "Ziad")
    new_vendor = [p for p in odoo.records["res.partner"].values() if p["name"] == "Najd Catering House"]
    assert len(new_vendor) == 1
    assert odoo.pos()[0]["partner_id"] == new_vendor[0]["id"]


def test_human_picks_vendor_when_unsure(store, odoo):
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "vendor_name": "Riyadh Grip and Light"}))
    assert r["status"] == "needs_human"
    with pytest.raises(ValueError):
        approve(store, odoo, r["run_id"], "Ziad")  # can't approve until a vendor is chosen
    resolve_needs_human(store, r["run_id"], 8, "Riyadh Grip & Lighting")
    approve(store, odoo, r["run_id"], "Ziad")
    assert odoo.pos()[0]["partner_id"] == 8


# ---- approve exactly the plan that was shown ----

def test_approving_with_the_shown_plan_hash_writes_the_po(store, odoo):
    r = run(store, odoo)
    po_id = approve_run(store, odoo, r["run_id"], "Ziad", plan_hash(r["plan_json"]))
    assert [po["id"] for po in odoo.pos()] == [po_id]
    assert store.get_run(r["run_id"])["status"] == "done"


def test_plan_changed_after_the_page_loaded_is_refused(store, odoo):
    """The approver opens the page and sees plan A. Before they click, the vendor question is
    re-opened and answered differently, so the plan is rebuilt as plan B. Their click must not
    run plan B. (Today nothing re-opens a question, but the safety must not depend on that.)"""
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "vendor_name": "Riyadh Grip and Light"}))
    resolve_needs_human(store, r["run_id"], 1, "Riyadh Grip Co")
    seen = plan_hash(store.get_run(r["run_id"])["plan_json"])  # the page is opened here

    store.update_run(r["run_id"], status="needs_human")  # someone re-opens the question...
    resolve_needs_human(store, r["run_id"], 8, "Riyadh Grip & Lighting")  # ...and picks another vendor

    with pytest.raises(ValueError, match="plan changed"):
        approve_run(store, odoo, r["run_id"], "Ziad", seen)
    assert odoo.pos() == []  # nothing written
    assert store.get_run(r["run_id"])["status"] == "pending_approval"  # still waiting for a human
    ops = [a["operation"] for a in store.audit_rows(r["run_id"])]
    assert "refused: plan changed since you viewed it" in ops and "approve" not in ops


@pytest.mark.parametrize("shown", ["", None, "abcd1234", "0" * 64])
def test_a_wrong_or_missing_plan_hash_is_refused(store, odoo, shown):
    r = run(store, odoo)
    with pytest.raises(ValueError, match="plan changed"):
        approve_run(store, odoo, r["run_id"], "Ziad", shown)
    assert odoo.pos() == []
    assert store.get_run(r["run_id"])["status"] == "pending_approval"


# ---- idempotency ----

def test_approving_twice_does_not_make_a_second_po(store, odoo):
    r = run(store, odoo)
    approve(store, odoo, r["run_id"], "Ziad")
    with pytest.raises(ValueError):
        approve(store, odoo, r["run_id"], "Ziad")
    assert len(odoo.pos()) == 1


def test_lost_answer_then_retry_makes_no_duplicate(store, odoo):
    """Odoo creates the PO, but the connection drops before we get the answer.
    We don't know if it worked, so we retry. The retry must find the PO, not make a second one."""
    r = run(store, odoo)
    odoo.lose_next_create_answer = True
    with pytest.raises(ConnectionResetError):
        approve(store, odoo, r["run_id"], "Ziad")
    assert store.get_run(r["run_id"])["status"] == "write_failed"
    assert len(odoo.pos()) == 1  # it really was created

    po_id = approve(store, odoo, r["run_id"], "Ziad")  # retry
    assert len(odoo.pos()) == 1  # still one
    assert po_id == odoo.pos()[0]["id"]
    assert store.get_run(r["run_id"])["status"] == "done"


def test_two_approvals_at_the_same_moment_make_one_po(store, odoo, monkeypatch):
    """A double-click, or two approvers at once. Only one of them may write."""
    r = run(store, odoo)
    real_create = odoo.create

    def slow_create(model, values):
        time.sleep(0.1)  # make the two requests overlap
        return real_create(model, values)
    monkeypatch.setattr(odoo, "create", slow_create)

    results = []

    def click():
        try:
            results.append(approve(store, odoo, r["run_id"], "Ziad"))
        except ValueError:
            results.append("refused")
    threads = [threading.Thread(target=click) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(odoo.pos()) == 1
    assert results.count("refused") == 1


def test_blank_approver_name_is_refused(store, odoo):
    r = run(store, odoo)
    with pytest.raises(ValueError):
        approve(store, odoo, r["run_id"], "   ")
    assert odoo.pos() == []
    assert store.get_run(r["run_id"])["status"] == "pending_approval"


def test_unexpected_error_leaves_the_run_retryable(store, odoo, monkeypatch):
    r = run(store, odoo)
    def broken_create(model, values):
        raise KeyError("a bug we didn't expect")
    monkeypatch.setattr(odoo, "create", broken_create)
    with pytest.raises(KeyError):
        approve(store, odoo, r["run_id"], "Ziad")
    assert store.get_run(r["run_id"])["status"] == "write_failed"  # not stuck in 'writing'


def test_a_failed_email_is_tried_again_on_the_next_poll(store, odoo):
    first = run(store, odoo, client=FakeAnthropic(stop_reason="refusal"))
    assert first["status"] == "failed"
    second = run(store, odoo)  # same email, next poll
    assert second["run_id"] == first["run_id"]  # same run, not a new one
    assert second["status"] == "pending_approval"


def test_the_agents_own_reply_is_not_read_as_a_request(store, odoo):
    client = FakeAnthropic()
    assert run(store, odoo, client=client, sender="procurement-agent@sadaf.example") is None
    assert client.sent == []
