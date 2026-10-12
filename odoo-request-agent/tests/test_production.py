"""Every PO line is charged to the right production (an Odoo analytic account)."""

import pytest

from odoo_agent.pipeline import resolve_needs_human
from odoo_agent.resolve import resolve_production, resolve_products

from .conftest import NORMAL_REQUEST, FakeAnthropic, approve
from .test_pipeline import run


@pytest.mark.parametrize("written", ["Rimal Al-Khobar", "rimal al khobar", "رمال الخبر", "RML-S1",
                                     "the Rimal Al-Khobar series", "مسلسل رمال الخبر"])
def test_production_is_found_in_english_arabic_or_by_code(odoo, written):
    result = resolve_production(odoo, written)
    assert result["status"] == "matched"
    assert result["analytic_id"] == odoo.production_ids["RML-S1"] and result["code"] == "RML-S1"


def test_arabic_spelling_variants_still_match(odoo):
    # ة written as ه, the way many people type it
    assert resolve_production(odoo, "سهره الخميس")["code"] == "SHK-S3"


def test_unsure_production_goes_to_a_human_with_every_production_listed(odoo):
    before = dict(odoo.records["account.analytic.account"])
    result = resolve_production(odoo, "رمال")  # too short to be sure
    assert result["status"] == "needs_human"
    assert [c["code"] for c in result["candidates"]][0] == "RML-S1"  # best guess first
    assert len(result["candidates"]) == 3
    assert odoo.records["account.analytic.account"] == before  # the agent never creates one


def test_every_po_line_is_charged_to_the_production(store, odoo):
    r = run(store, odoo)
    line = r["plan_json"][-1]["values"]["order_line"][0][2]
    assert line["analytic_distribution"] == {str(odoo.production_ids["RML-S1"]): 100}
    approve(store, odoo, r["run_id"])
    po_line = odoo.pos()[0]["order_line"][0][2]
    assert po_line["analytic_distribution"] == {str(odoo.production_ids["RML-S1"]): 100}


def test_unclear_production_waits_for_a_person_then_is_charged(store, odoo):
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "production": "رمال"}))
    assert r["status"] == "needs_human"
    assert "analytic_distribution" not in r["plan_json"][-1]["values"]["order_line"][0][2]
    with pytest.raises(ValueError):
        approve(store, odoo, r["run_id"])  # can't approve before the production is chosen

    resolve_needs_human(store, r["run_id"], production_id=odoo.production_ids["SHK-S3"], chosen_by="Noura")
    line = store.get_run(r["run_id"])["plan_json"][-1]["values"]["order_line"][0][2]
    assert line["analytic_distribution"] == {str(odoo.production_ids["SHK-S3"]): 100}
    assert store.audit_rows(r["run_id"])[-1]["actor"] == "human:Noura"


def test_answering_without_choosing_the_production_is_refused(store, odoo):
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "production": "رمال"}))
    with pytest.raises(ValueError, match="production"):
        resolve_needs_human(store, r["run_id"])
    with pytest.raises(ValueError, match="production"):
        resolve_needs_human(store, r["run_id"], production_id=999)  # not one of the choices
    assert store.get_run(r["run_id"])["status"] == "needs_human"


def test_vendor_question_must_be_answered_too(store, odoo):
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "vendor_name": "Riyadh Grip and Light"}))
    with pytest.raises(ValueError, match="vendor"):
        resolve_needs_human(store, r["run_id"])  # no vendor picked, and "new vendor" not chosen
    resolve_needs_human(store, r["run_id"], new_vendor=True)
    assert store.get_run(r["run_id"])["resolution_json"]["vendor"]["status"] == "new"


def test_unknown_item_uses_the_product_for_its_category(odoo):
    [line] = resolve_products(odoo, ["Location permit, Al-Balad house"], ["location"])
    assert line["product_name"] == "Location Fee" and line["free_text"]
    [line] = resolve_products(odoo, ["Something odd"], ["transport"])  # no Transport product in the fake
    assert line["product_name"] == "Production Service"


def test_missing_production_asks_the_sender(store, odoo):
    r = run(store, odoo, client=FakeAnthropic({**NORMAL_REQUEST, "production": None}))
    assert r["status"] == "needs_info"
    assert "production" in r["reply_draft"]
