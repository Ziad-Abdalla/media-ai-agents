import pytest

from odoo_agent.permissions import execute
from odoo_agent.pipeline import process_email
from odoo_agent.rollback import RollbackRefused, rollback

from .conftest import NORMAL_REQUEST, FakeAnthropic, approve, make_email


def approved_run(store, odoo, request=NORMAL_REQUEST):
    run_id = process_email(make_email(), client=FakeAnthropic(request), odoo=odoo, store=store)
    approve(store, odoo, run_id, "Ziad")
    return run_id


def test_rollback_deletes_the_draft_po_and_archives_the_new_vendor(store, odoo):
    run_id = approved_run(store, odoo, {**NORMAL_REQUEST, "vendor_name": "Najd Catering House"})
    assert len(odoo.pos()) == 1

    rollback(store, odoo, run_id)
    assert odoo.pos() == []
    vendor = [p for p in odoo.records["res.partner"].values() if p["name"] == "Najd Catering House"][0]
    assert vendor["active"] is False
    ops = [row["operation"] for row in store.audit_rows(run_id)]
    assert "rollback_delete_po" in ops and "rollback_archive_vendor" in ops
    assert store.get_run(run_id)["status"] == "rolled_back"


def test_rollback_restores_before_values_of_an_update(store, odoo):
    run_id = approved_run(store, odoo)
    po_id = odoo.pos()[0]["id"]
    other = odoo.create("purchase.order", {"partner_ref": "OLD-REF"})  # a PO the agent didn't make
    execute("update_purchase_order", odoo=odoo, store=store, run_id=run_id, approved_by="Ziad",
            po_id=other, values={"partner_ref": "NEW-REF"})
    assert odoo.records["purchase.order"][other]["partner_ref"] == "NEW-REF"

    rollback(store, odoo, run_id)
    assert odoo.records["purchase.order"][other]["partner_ref"] == "OLD-REF"  # restored
    assert po_id not in odoo.records["purchase.order"]                       # agent's PO gone


def test_rollback_finds_a_po_whose_create_answer_was_lost(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    odoo.lose_next_create_answer = True
    with pytest.raises(ConnectionResetError):
        approve(store, odoo, run_id, "Ziad")
    rollback(store, odoo, run_id)
    assert odoo.pos() == []


def test_rollback_refuses_if_someone_confirmed_the_po(store, odoo):
    run_id = approved_run(store, odoo)
    po = odoo.pos()[0]
    odoo.write("purchase.order", po["id"], {"state": "purchase"})
    with pytest.raises(RollbackRefused):
        rollback(store, odoo, run_id)
    assert len(odoo.pos()) == 1


def test_rollback_works_even_with_the_kill_switch_on(store, odoo, monkeypatch):
    run_id = approved_run(store, odoo)
    monkeypatch.setenv("AGENT_WRITES_ENABLED", "false")
    rollback(store, odoo, run_id)
    assert odoo.pos() == []


def test_rollback_archives_a_vendor_whose_create_answer_was_lost(store, odoo):
    new_vendor = {**NORMAL_REQUEST, "vendor_name": "Najd Catering House"}
    run_id = process_email(make_email(), client=FakeAnthropic(new_vendor), odoo=odoo, store=store)
    odoo.lose_next_create_answer = True  # the vendor is saved, but we never hear back
    with pytest.raises(ConnectionResetError):
        approve(store, odoo, run_id, "Ziad")
    approve(store, odoo, run_id, "Ziad")  # retry finds the vendor by its key: no second vendor
    vendors = [p for p in odoo.records["res.partner"].values() if p["name"] == "Najd Catering House"]
    assert len(vendors) == 1

    rollback(store, odoo, run_id)
    assert vendors[0]["active"] is False
    assert odoo.pos() == []
