import re

from fastapi.testclient import TestClient

from odoo_agent.pipeline import process_email
from odoo_agent.plan import plan_hash
from odoo_agent.web import create_app

from .conftest import NORMAL_REQUEST, FakeAnthropic, make_email


def shown_hash(web, run_id):
    """The hidden plan_hash the approval page put in this run's Approve form."""
    page = web.get(f"/?run={run_id}").text
    return re.search(r'name="plan_hash" value="([0-9a-f]{64})"', page).group(1)


def test_page_shows_the_plan_and_approve_writes_the_po(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))

    page = web.get("/").text
    assert run_id in page and "pending_approval" in page and "APR-2026-0412" in page
    assert "Camera Crane Rental" in page  # the matched Odoo product is shown
    assert odoo.pos() == []

    assert "plan #" + shown_hash(web, run_id)[:8] in page  # the person can see which plan
    web.post(f"/runs/{run_id}/approve", data={"approver": "Ziad", "plan_hash": shown_hash(web, run_id)})
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


def test_approve_without_the_plan_hash_is_refused(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))
    page = web.post(f"/runs/{run_id}/approve", data={"approver": "Ziad"}).text
    assert "plan changed after you opened the page" in page
    assert odoo.pos() == []
    assert store.get_run(run_id)["status"] == "pending_approval"


def test_a_rejected_or_rolled_back_run_cannot_be_reopened(store, odoo):
    from odoo_agent.rollback import rollback

    web = TestClient(create_app(store, lambda: odoo))
    rejected = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web.post(f"/runs/{rejected}/reject", data={"approver": "Ziad"})

    other_order = {**NORMAL_REQUEST, "approval_reference": "APR-2026-0999"}
    rolled = process_email(make_email(message_id="<other@sadaf.example>"),
                           client=FakeAnthropic(other_order), odoo=odoo, store=store)
    web.post(f"/runs/{rolled}/approve", data={"approver": "Ziad", "plan_hash": shown_hash(web, rolled)})
    assert len(odoo.pos()) == 1
    rollback(store, odoo, rolled)

    for run_id in (rejected, rolled):
        web.post(f"/runs/{run_id}/resolve", data={"partner": "confirm_resend", "approver": "Ziad"})
        current = plan_hash(store.get_run(run_id)["plan_json"])  # even with the right hash
        web.post(f"/runs/{run_id}/approve", data={"approver": "Ziad", "plan_hash": current})
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


def test_model_notes_are_a_plain_box_and_only_injections_are_red(store, odoo):
    noted = {**NORMAL_REQUEST, "confidence_notes": "Year not given; assumed 2026."}
    run_id = process_email(make_email(), client=FakeAnthropic(noted), odoo=odoo, store=store)
    page = TestClient(create_app(store, lambda: odoo)).get(f"/?run={run_id}").text
    assert '<p class="note">AI\'s notes: Year not given; assumed 2026.</p>' in page
    assert 'class="warn"' not in page
