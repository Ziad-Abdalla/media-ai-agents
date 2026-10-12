"""The whole flow with a fake model and a fake Odoo: statuses, duplicates, idempotency."""

import pytest

from odoo_agent.pipeline import approve_run, choose_vendor, process_email

from .conftest import NORMAL_REQUEST, FakeAnthropic, make_email


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
    po_id = approve_run(store, odoo, r["run_id"], "Ziad")
    [po] = odoo.pos()
    assert po["id"] == po_id and po["state"] == "draft"
    assert store.get_run(r["run_id"])["status"] == "done"


def test_missing_fields_ask_for_info_and_draft_a_reply(store, odoo):
    incomplete = {**NORMAL_REQUEST, "approval_reference": None,
                  "items": [{"name": "Lighting kit", "quantity": None, "unit_price": None,
                             "currency": None}]}
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
    approve_run(store, odoo, r["run_id"], "Ziad")
    new_vendor = [p for p in odoo.records["res.partner"].values() if p["name"] == "Najd Catering House"]
    assert len(new_vendor) == 1
    assert odoo.pos()[0]["partner_id"] == new_vendor[0]["id"]


def test_human_picks_vendor_when_unsure(store, odoo):
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "vendor_name": "Riyadh Grip and Light"}))
    assert r["status"] == "needs_human"
    with pytest.raises(ValueError):
        approve_run(store, odoo, r["run_id"], "Ziad")  # can't approve until a vendor is chosen
    choose_vendor(store, r["run_id"], 8, "Riyadh Grip & Lighting")
    approve_run(store, odoo, r["run_id"], "Ziad")
    assert odoo.pos()[0]["partner_id"] == 8


# ---- idempotency ----

def test_approving_twice_does_not_make_a_second_po(store, odoo):
    r = run(store, odoo)
    approve_run(store, odoo, r["run_id"], "Ziad")
    with pytest.raises(ValueError):
        approve_run(store, odoo, r["run_id"], "Ziad")
    assert len(odoo.pos()) == 1


def test_lost_answer_then_retry_makes_no_duplicate(store, odoo):
    """Odoo creates the PO, but the connection drops before we get the answer.
    We don't know if it worked, so we retry. The retry must find the PO, not make a second one."""
    r = run(store, odoo)
    odoo.lose_next_create_answer = True
    with pytest.raises(ConnectionResetError):
        approve_run(store, odoo, r["run_id"], "Ziad")
    assert store.get_run(r["run_id"])["status"] == "write_failed"
    assert len(odoo.pos()) == 1  # it really was created

    po_id = approve_run(store, odoo, r["run_id"], "Ziad")  # retry
    assert len(odoo.pos()) == 1  # still one
    assert po_id == odoo.pos()[0]["id"]
    assert store.get_run(r["run_id"])["status"] == "done"
