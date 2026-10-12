from fastapi.testclient import TestClient

from odoo_agent.pipeline import process_email
from odoo_agent.web import create_app

from .conftest import NORMAL_REQUEST, FakeAnthropic, make_email


def test_page_shows_the_plan_and_approve_writes_the_po(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))

    page = web.get("/").text
    assert run_id in page and "pending_approval" in page and "APR-2026-0412" in page
    assert "Camera Crane Rental" in page  # the matched Odoo product is shown
    assert odoo.pos() == []

    web.post(f"/runs/{run_id}/approve", data={"approver": "Ziad"})
    assert len(odoo.pos()) == 1
    assert store.get_run(run_id)["approved_by"] == "Ziad"


def test_reject_writes_nothing(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))
    web.post(f"/runs/{run_id}/reject", data={"approver": "Ziad"})
    assert odoo.pos() == []
    assert store.get_run(run_id)["status"] == "rejected"


def test_approve_without_a_name_is_refused(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))
    assert web.post(f"/runs/{run_id}/approve", data={}).status_code == 422
    assert odoo.pos() == []


def test_a_rejected_or_rolled_back_run_cannot_be_reopened(store, odoo):
    from odoo_agent.rollback import rollback

    web = TestClient(create_app(store, lambda: odoo))
    rejected = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web.post(f"/runs/{rejected}/reject", data={"approver": "Ziad"})

    other_order = {**NORMAL_REQUEST, "approval_reference": "APR-2026-0999"}
    rolled = process_email(make_email(message_id="<other@sadaf.example>"),
                           client=FakeAnthropic(other_order), odoo=odoo, store=store)
    web.post(f"/runs/{rolled}/approve", data={"approver": "Ziad"})
    rollback(store, odoo, rolled)

    for run_id in (rejected, rolled):
        web.post(f"/runs/{run_id}/resolve", data={"partner": "confirm_resend"})
        web.post(f"/runs/{run_id}/approve", data={"approver": "Ziad"})
    assert odoo.pos() == []
    assert store.get_run(rejected)["status"] == "rejected"
    assert store.get_run(rolled)["status"] == "rolled_back"


def test_a_reply_is_sent_only_once(store, odoo, monkeypatch):
    from odoo_agent import actions

    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def send_message(self, msg): sent.append(msg["To"])
    monkeypatch.setattr(actions.smtplib, "SMTP", FakeSMTP)

    incomplete = {**NORMAL_REQUEST, "approval_reference": None}
    run_id = process_email(make_email(), client=FakeAnthropic(incomplete), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))
    web.post(f"/runs/{run_id}/send_reply", data={"approver": "Ziad"})
    web.post(f"/runs/{run_id}/send_reply", data={"approver": "Ziad"})
    assert sent == ["noura@sadaf.example"]
    assert store.get_run(run_id)["status"] == "reply_sent"
