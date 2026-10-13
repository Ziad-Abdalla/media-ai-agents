import base64

import httpx

from inbox_agent.inbox import DatasetInbox, GmailInbox, MailpitInbox, build_mime, parse_raw

ITEM = {"id": "t1", "from": {"name": "عمر حداد", "email": "Omar.Haddad@sadaf.example"},
        "to": ["ceo-office@sadaf.example"], "cc": ["lama.ghamdi@sadaf.example"],
        "date": "2026-10-06T11:00:00+03:00", "subject": "رد: مواصفات التسليم",
        "message_id": "<b@sadaf.example>", "in_reply_to": "<a@mbc-group.example>",
        "references": ["<root@mbc-group.example>", "<a@mbc-group.example>"],
        "body": "تمام، لمى بتتابع.", "html_hidden": "سر مخفي",
        "attachments": [{"filename": "specs.txt", "text": "ProRes 422 HQ"}]}


def test_raw_message_round_trip_keeps_thread_headers_and_attachment_text():
    e = parse_raw(build_mime(ITEM).as_bytes(), "t1")
    assert e.from_addr == "omar.haddad@sadaf.example"   # lower-cased
    assert e.in_reply_to == "<a@mbc-group.example>"
    assert e.references == ["<root@mbc-group.example>", "<a@mbc-group.example>"]
    assert e.cc == ["lama.ghamdi@sadaf.example"]
    assert e.attachments[0].filename == "specs.txt" and "ProRes" in e.attachments[0].text
    assert "سر مخفي" in e.html_text and "سر مخفي" not in e.body   # hidden HTML text is still read
    assert e.date.startswith("2026-10-06T11:00")


def test_dataset_inbox_parses_every_email_in_the_dataset():
    emails = DatasetInbox().fetch()
    assert len(emails) >= 40
    assert all(e.message_id.startswith("<") and e.from_addr for e in emails)


def test_mailpit_inbox_reads_raw_messages_and_skips_the_agents_own_mail():
    own = {**ITEM, "id": "t2", "from": {"name": "agent", "email": "inbox-agent@sadaf.example"},
           "message_id": "<c@sadaf.example>"}
    other = {**ITEM, "id": "t3", "to": ["someone@sadaf.example"], "cc": [], "message_id": "<d@x>"}
    raws = {"1": build_mime(ITEM).as_bytes(), "2": build_mime(own).as_bytes(),
            "3": build_mime(other).as_bytes()}
    tagged = []

    def handler(request: httpx.Request):
        if request.url.path == "/api/v1/messages":
            return httpx.Response(200, json={"total": 3, "messages": [{"ID": k} for k in raws]})
        if request.url.path == "/api/v1/tags":
            tagged.append(request.content)
            return httpx.Response(200, json={})
        mid = request.url.path.split("/")[4]
        return httpx.Response(200, content=raws[mid])

    inbox = MailpitInbox("http://mailpit", office_inbox="ceo-office@sadaf.example",
                         agent_address="inbox-agent@sadaf.example",
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    emails = inbox.fetch()
    assert [e.source_id for e in emails] == ["1"]
    inbox.add_tags("1", ["urgent_action"])
    assert b"urgent_action" in tagged[0]


class FakeGmail:
    """Just enough of the Gmail API client: users().messages().list/get(...).execute()."""

    def __init__(self, raw):
        self.raw = raw
        self.calls = []
        self._next = None

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kw):
        self.calls.append(("list", kw))
        self._next = {"messages": [{"id": "g1"}]}
        return self

    def get(self, **kw):
        self.calls.append(("get", kw))
        self._next = {"id": "g1", "raw": base64.urlsafe_b64encode(self.raw).decode()}
        return self

    def execute(self):
        return self._next


def test_gmail_inbox_uses_the_raw_format_and_the_same_parser():
    svc = FakeGmail(build_mime(ITEM).as_bytes())
    emails = GmailInbox(svc, label="ceo-office").fetch()
    assert emails[0].in_reply_to == "<a@mbc-group.example>" and emails[0].source_id == "g1"
    assert ("list", {"userId": "me", "q": "label:ceo-office", "maxResults": 50}) in svc.calls
    assert svc.calls[1][1]["format"] == "raw"
