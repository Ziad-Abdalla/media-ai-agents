"""The extraction eval: labelled synthetic emails, field-by-field scoring. No real model here."""

import json

from odoo_agent.evaluate import SAMPLES_FILE, _accounts, check_fields, run_eval
from odoo_agent.models import PurchaseRequest

from .conftest import NORMAL_REQUEST, FakeAnthropic

SAMPLES = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
CRANE = next(s for s in SAMPLES["samples"] if s["id"] == "crane")


def test_samples_are_labelled_synthetic_and_complete():
    assert "SYNTHETIC" in SAMPLES["_note"]
    for s in SAMPLES["samples"]:
        assert s["sender"].endswith("@sadaf.example")
        if s.get("eval", True):
            assert set(s["expected"]) >= {"vendor_name", "production", "approval_reference", "needed_by",
                                          "currency", "items", "flags_injection"}


def test_a_right_answer_scores_every_field():
    got = PurchaseRequest.model_validate(NORMAL_REQUEST)
    assert all(check_fields(got, CRANE["expected"], _accounts()).values())


def test_each_wrong_field_is_caught():
    wrong = {**NORMAL_REQUEST, "approval_reference": "APR-2026-9999", "production": "Bayt Al-Jadd",
             "items": [{**NORMAL_REQUEST["items"][0], "unit_price": 3000}]}
    fields = check_fields(PurchaseRequest.model_validate(wrong), CRANE["expected"], _accounts())
    assert {f for f, ok in fields.items() if not ok} == {"approval_reference", "production", "unit_prices"}


def test_being_unsure_is_right_when_the_label_says_unsure():
    unclear = next(s for s in SAMPLES["samples"] if s["id"] == "unclear-production")
    got = PurchaseRequest.model_validate({**NORMAL_REQUEST, "production": "رمال"})
    assert check_fields(got, unclear["expected"], _accounts())["production"]


def test_run_eval_scores_and_records_cost_under_its_own_name():
    result = run_eval(FakeAnthropic())  # always answers "the crane email"
    s = result["summary"]
    assert s["emails"] == len([x for x in SAMPLES["samples"] if x.get("eval", True)])
    assert s["readings_all_correct"] >= 1  # the crane email itself
    assert 0 < s["field_accuracy_pct"] < 100
    assert s["cost_usd"] > 0  # recorded in the ledger as eval_extract_purchase_request
    assert any(m["id"] == "arabic-lights" for m in result["misses"])
