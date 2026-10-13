"""Gmail and Mailpit parsing, with the network mocked out."""

import base64
from unittest.mock import MagicMock

from odoo_agent import inbox
from odoo_agent.inbox import GMAIL_SCOPES, GmailInbox, MailpitInbox, parse_gmail_message


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode()


GMAIL_MESSAGE = {
    "id": "18f0a",
    "payload": {
        "mimeType": "multipart/mixed",
        "headers": [
            {"name": "From", "value": "Noura Al-Harbi <Noura@Sadaf.example>"},
            {"name": "Subject", "value": "Crane rental"},
            {"name": "Message-ID", "value": "<abc@sadaf.example>"},
            {"name": "Date", "value": "Mon, 12 Oct 2026 10:00:00 +0300"},
        ],
        "parts": [{  # text and html nested one level down, like real Gmail
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": b64("Please order 2 days of crane.")}},
                {"mimeType": "text/html", "body": {"data": b64("<p>Please order</p>")}},
            ],
        }],
    },
}


def test_parse_gmail_message():
    email = parse_gmail_message(GMAIL_MESSAGE)
    assert email.sender == "noura@sadaf.example"  # just the address, lower case
    assert email.message_id == "<abc@sadaf.example>"
    assert email.subject == "Crane rental"
    assert email.body == "Please order 2 days of crane."


def test_gmail_inbox_reads_only_the_label():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.return_value = {"messages": [{"id": "18f0a"}]}
    messages.get.return_value.execute.return_value = GMAIL_MESSAGE

    emails = GmailInbox(service, label="purchase-requests").fetch()
    assert [e.subject for e in emails] == ["Crane rental"]
    assert messages.list.call_args.kwargs["q"] == "label:purchase-requests"


def test_gmail_permission_is_read_only():
    assert GMAIL_SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_mailpit_inbox(monkeypatch):
    def fake_get(url, timeout):
        response = MagicMock()
        if url.endswith("/api/v1/messages"):
            response.json.return_value = {"messages": [{"ID": "m1"}]}
        else:
            response.json.return_value = {
                "MessageID": "abc@sadaf.example", "From": {"Address": "Noura@sadaf.example"},
                "Subject": "Crane", "Text": "body", "Date": "2026-10-12T10:00:00+03:00"}
        return response

    monkeypatch.setattr(inbox.httpx, "get", fake_get)
    [email] = MailpitInbox("http://mailpit").fetch()
    assert email.sender == "noura@sadaf.example" and email.body == "body"
