from odoo_agent.models import PurchaseRequest
from odoo_agent.validate import draft_needs_info_reply, sender_allowed, validate

from .conftest import NORMAL_REQUEST, make_email


def request(**changes):
    data = {**NORMAL_REQUEST, **changes}
    return PurchaseRequest.model_validate(data)


def item(**changes):
    return [{**NORMAL_REQUEST["items"][0], **changes}]


def test_complete_request_has_no_problems():
    assert validate(request(), make_email()) == []


def test_missing_fields_are_each_listed():
    problems = validate(request(approval_reference=None, vendor_name=None,
                                items=item(unit_price=None)), make_email())
    assert any("approval reference" in p for p in problems)
    assert any("vendor name" in p for p in problems)
    assert any("unit price" in p for p in problems)


def test_numbers_must_be_positive():
    problems = validate(request(items=item(quantity=-2)), make_email())
    assert any("quantity" in p for p in problems)


def test_currency_must_be_on_the_allow_list():
    problems = validate(request(items=item(currency="BTC")), make_email())
    assert any("currency" in p for p in problems)


def test_date_in_the_past_or_far_future_is_rejected():
    assert validate(request(needed_by="2026-01-01"), make_email())
    assert validate(request(needed_by="2031-01-01"), make_email())
    assert validate(request(needed_by="next tuesday"), make_email())


def test_only_internal_senders():
    assert sender_allowed(make_email(sender="noura@sadaf.example"))
    assert not sender_allowed(make_email(sender="noura@sadaf.example.evil.com"))
    assert not sender_allowed(make_email(sender="someone@gmail.com"))


def test_reply_asks_for_exactly_the_missing_fields():
    reply = draft_needs_info_reply(make_email(subject="Lights"), ["vendor name", "approval reference"])
    assert "- vendor name" in reply and "- approval reference" in reply
    assert "Lights" in reply
