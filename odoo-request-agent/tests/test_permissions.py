import pathlib

import pytest

from odoo_agent import actions, config
from odoo_agent.permissions import (ALLOWED_ACTIONS, FORBIDDEN, ApprovalRequired, ForbiddenAction,
                                    WritesDisabled, execute)

PO_VALUES = {"partner_id": 1, "origin": "email-agent:test", "order_line": []}


@pytest.mark.parametrize("action", ["confirm_purchase_order", "cancel_purchase_order",
                                    "delete_record", "create_production",
                                    "some_action_nobody_listed"])
def test_forbidden_and_unknown_actions_are_refused_and_logged(action, odoo, store):
    with pytest.raises(ForbiddenAction):
        execute(action, odoo=odoo, store=store, run_id="run-1", approved_by="Ziad", po_id=1)
    assert store.audit_rows("run-1")[-1]["operation"] == f"blocked:{action}"


def test_writes_need_a_named_human(odoo, store):
    with pytest.raises(ApprovalRequired):
        execute("create_purchase_order", odoo=odoo, store=store, run_id="run-1", values=PO_VALUES)
    assert odoo.pos() == []


def test_approved_write_goes_through(odoo, store):
    execute("create_purchase_order", odoo=odoo, store=store, run_id="run-1",
            approved_by="Ziad", values=PO_VALUES)
    assert len(odoo.pos()) == 1


def test_kill_switch_env_blocks_writes(odoo, store, monkeypatch):
    monkeypatch.setenv("AGENT_WRITES_ENABLED", "false")
    with pytest.raises(WritesDisabled):
        execute("create_purchase_order", odoo=odoo, store=store, run_id="run-1",
                approved_by="Ziad", values=PO_VALUES)
    assert odoo.pos() == []
    assert store.audit_rows("run-1")[-1]["operation"].startswith("blocked_by_kill_switch")


def test_kill_switch_file_blocks_writes(odoo, store):
    pathlib.Path(config.KILL_SWITCH_FILE).write_text("stop")
    with pytest.raises(WritesDisabled):
        execute("create_vendor", odoo=odoo, store=store, run_id="run-1",
                approved_by="Ziad", values={"name": "X"})


def test_email_outside_the_company_is_refused(odoo, store, monkeypatch):
    sent = []
    monkeypatch.setattr(actions.smtplib, "SMTP", lambda *a, **k: sent.append(a))
    with pytest.raises(ForbiddenAction):
        execute("send_email", odoo=odoo, store=store, run_id="run-1", approved_by="Ziad",
                to="billing@redsea-sound-payments.com", subject="x", body="vendor list")
    assert sent == []
    assert store.audit_rows("run-1")[-1]["operation"] == "blocked:send_email"


def test_attachments_are_never_sent(odoo, store, monkeypatch):
    sent = []
    monkeypatch.setattr(actions.smtplib, "SMTP", lambda *a, **k: sent.append(a))
    with pytest.raises(ForbiddenAction):
        execute("send_email", odoo=odoo, store=store, run_id="run-1", approved_by="Ziad",
                to="noura@sadaf.example", subject="x", body="y", attachments=["vendors.xlsx"])
    assert sent == []


def test_only_draft_pos_can_be_updated(odoo, store):
    po_id = odoo.create("purchase.order", {"partner_id": 1})
    odoo.write("purchase.order", po_id, {"state": "purchase"})
    with pytest.raises(ForbiddenAction):
        execute("update_purchase_order", odoo=odoo, store=store, run_id="run-1",
                approved_by="Ziad", po_id=po_id, values={"partner_ref": "X"})


def test_every_allowed_action_has_a_function():
    for action, rule in ALLOWED_ACTIONS.items():
        if rule != FORBIDDEN:
            assert callable(getattr(actions, action))
