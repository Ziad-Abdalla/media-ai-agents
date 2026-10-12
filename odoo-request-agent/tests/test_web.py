from fastapi.testclient import TestClient

from odoo_agent.pipeline import process_email
from odoo_agent.web import create_app

from .conftest import FakeAnthropic, make_email


def test_page_shows_the_plan_and_approve_writes_the_po(store, odoo):
    run_id = process_email(make_email(), client=FakeAnthropic(), odoo=odoo, store=store)
    web = TestClient(create_app(store, lambda: odoo))

    page = web.get("/").text
    assert run_id in page and "pending_approval" in page and "APR-2026-0412" in page
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
