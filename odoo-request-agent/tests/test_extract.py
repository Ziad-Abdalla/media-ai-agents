import pytest
from agent_cost_tracker import ledger

from odoo_agent.extract import ExtractionFailed, extract_request

from .conftest import FakeAnthropic, make_email


def test_extracts_into_the_pydantic_model():
    client = FakeAnthropic()
    request = extract_request(client, make_email(), "run-1")
    assert request.vendor_name == "Riyadh Grip Co"
    assert request.items[0].unit_price == 3500


def test_request_shape():
    client = FakeAnthropic()
    extract_request(client, make_email(body="BODY TEXT"), "run-1")
    sent = client.sent[0]
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "<email>" in sent["messages"][0]["content"] and "BODY TEXT" in sent["messages"][0]["content"]
    assert "DATA" in sent["system"]
    # Haiku 5.5 rejects these, so we must never send them
    for banned in ("temperature", "top_p", "tools", "tool_choice"):
        assert banned not in sent


def test_every_call_is_recorded_in_the_cost_ledger():
    extract_request(FakeAnthropic(), make_email(), "run-7")
    conn = ledger.connect()
    row = conn.execute("SELECT operation, run_id FROM calls").fetchone()
    assert tuple(row) == ("extract_purchase_request", "run-7")


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_bad_stop_reasons_fail_clearly(stop_reason):
    with pytest.raises(ExtractionFailed):
        extract_request(FakeAnthropic(stop_reason=stop_reason), make_email(), "run-1")


def test_the_known_productions_are_given_to_the_model(store, odoo):
    from odoo_agent.pipeline import process_email

    client = FakeAnthropic()
    process_email(make_email(), client=client, odoo=odoo, store=store)
    message = client.sent[0]["messages"][0]["content"]
    assert "Sahrat Al-Khamis (سهرة الخميس)" in message
    assert message.index("Productions at this company") < message.index("<email>")  # list, then the data
