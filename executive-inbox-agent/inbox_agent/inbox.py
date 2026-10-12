"""Step 1a: where emails come from. Every source has the same method: fetch() -> list[Email].

All sources hand us the RAW message (RFC 822 bytes) and we parse it ourselves with one
function, parse_raw(). That way Mailpit, Gmail and the test dataset go through exactly the
same parsing code, including the headers thread linking needs (Message-ID, In-Reply-To,
References), the hidden text in the HTML part, and the text of attachments.

  MailpitInbox  the local test mail server (docker, port 8027). Can also add tags (labels).
  GmailInbox    a real Gmail label, read-only permission (gmail.readonly).
  DatasetInbox  data/emails.yaml turned into real MIME messages in memory (for eval).
"""

import base64
import os
import re
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import format_datetime, getaddresses, parseaddr, parsedate_to_datetime
from datetime import datetime
from html.parser import HTMLParser

import httpx
import yaml

from . import config
from .models import Attachment, Email

TEXT_ATTACHMENT_TYPES = ("text/", "application/json", "application/xml")


class _HTMLText(HTMLParser):
    """Collects ALL text in an HTML part, including text a mail client would hide
    (display:none, white-on-white). Hidden text is exactly where injections like to sit."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    p = _HTMLText()
    p.feed(html or "")
    return "\n".join(p.parts)


def _ids(value: str | None) -> list[str]:
    return re.findall(r"<[^<>\s]+>", value or "")


def parse_raw(raw: bytes, source_id: str = "") -> Email:
    msg = message_from_bytes(raw, policy=policy.default)
    body, html_text, attachments = "", "", []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True) or b""
            text = ""
            if ctype.startswith(TEXT_ATTACHMENT_TYPES) or (filename or "").lower().endswith((".txt", ".csv")):
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            # (PDF/DOCX text extraction would plug in here; the demo attaches the text layer.)
            attachments.append(Attachment(filename=filename or "unnamed", content_type=ctype,
                                          text=text, size=len(payload)))
        elif ctype == "text/plain" and not body:
            body = part.get_content()
        elif ctype == "text/html":
            html_text = html_to_text(part.get_content())

    try:
        date = parsedate_to_datetime(msg["Date"]).isoformat()
    except (TypeError, ValueError):
        date = ""
    name, addr = parseaddr(str(msg.get("From", "")))
    return Email(
        message_id=(_ids(msg.get("Message-ID")) or [f"<no-id-{source_id}@local>"])[0],
        from_addr=addr.lower(),
        from_name=name,
        to=[a.lower() for _, a in getaddresses([str(msg.get("To", ""))]) if a],
        cc=[a.lower() for _, a in getaddresses([str(msg.get("Cc", ""))]) if a],
        subject=str(msg.get("Subject", "")),
        date=date,
        body=body or html_text,
        in_reply_to=(_ids(msg.get("In-Reply-To")) or [None])[0],
        references=_ids(msg.get("References")),
        html_text=html_text,
        attachments=attachments,
        source_id=source_id,
    )


# ---------------------------------------------------------------- building MIME (dataset/seed)
def build_mime(item: dict) -> EmailMessage:
    """One dataset entry -> a real email message, the same shape a mail server would deliver."""
    msg = EmailMessage()
    sender = item["from"]
    msg["From"] = f'{sender.get("name", "")} <{sender["email"]}>'
    msg["To"] = ", ".join(item.get("to") or [])
    if item.get("cc"):
        msg["Cc"] = ", ".join(item["cc"])
    msg["Subject"] = item["subject"]
    msg["Date"] = format_datetime(datetime.fromisoformat(item["date"]))
    msg["Message-ID"] = item["message_id"]
    if item.get("in_reply_to"):
        msg["In-Reply-To"] = item["in_reply_to"]
    if item.get("references"):
        msg["References"] = " ".join(item["references"])
    msg["X-Dataset-Id"] = item["id"]
    msg.set_content(item["body"])
    if item.get("html_hidden"):
        visible = "".join(f"<p>{line}</p>" for line in item["body"].splitlines() if line.strip())
        msg.add_alternative(
            f'<html><body dir="auto">{visible}'
            f'<div style="display:none;color:#ffffff;font-size:1px">{item["html_hidden"]}</div>'
            f"</body></html>", subtype="html")
    for att in item.get("attachments") or []:
        msg.add_attachment(att["text"].encode("utf-8"), maintype="text", subtype="plain",
                           filename=att["filename"])
    return msg


def load_dataset(path: str = config.DATASET_FILE) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class DatasetInbox:
    """The synthetic dataset, parsed through the same parse_raw() as real mail."""

    def __init__(self, path: str = config.DATASET_FILE, only: list[str] | None = None):
        self.items = [i for i in load_dataset(path) if not only or i["id"] in only]

    def fetch(self) -> list[Email]:
        return [parse_raw(build_mime(i).as_bytes(), source_id=i["id"]) for i in self.items]


# ---------------------------------------------------------------- Mailpit
class MailpitInbox:
    """Reads the local Mailpit server. Skips mail the agent itself sent (briefings, replies),
    and mail not addressed to the office inbox."""

    def __init__(self, base_url: str = config.MAILPIT_URL, office_inbox: str = "",
                 agent_address: str = "", client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.office_inbox = office_inbox.lower()
        self.agent_address = agent_address.lower()
        self.http = client or httpx.Client(timeout=15)

    def fetch(self) -> list[Email]:
        emails, start = [], 0
        while True:
            page = self.http.get(f"{self.base_url}/api/v1/messages",
                                 params={"start": start, "limit": 200}).json()
            for summary in page.get("messages", []):
                raw = self.http.get(f"{self.base_url}/api/v1/message/{summary['ID']}/raw").content
                email = parse_raw(raw, source_id=summary["ID"])
                if self.agent_address and email.from_addr == self.agent_address:
                    continue
                if self.office_inbox and self.office_inbox not in email.to + email.cc:
                    continue
                emails.append(email)
            start += len(page.get("messages", []))
            if not page.get("messages") or start >= page.get("total", 0):
                break
        emails.sort(key=lambda e: e.date)  # oldest first, so replies come after what they answer
        return emails

    def add_tags(self, source_id: str, tags: list[str]) -> None:
        """Mailpit's version of Gmail labels. Visible in the Mailpit web UI."""
        self.http.put(f"{self.base_url}/api/v1/tags", json={"IDs": [source_id], "Tags": tags})


# ---------------------------------------------------------------- Gmail
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]  # read only, nothing else


def build_gmail_service(credentials_file="credentials.json", token_file="token.json"):
    """Log in to Gmail once in the browser, then reuse token.json. Both files are git-ignored."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


class GmailInbox:
    """Reads one Gmail label. Asks for format='raw' so the same parse_raw() is used."""

    def __init__(self, service, label: str = config.GMAIL_LABEL, max_results: int = 50):
        self.service = service
        self.label = label
        self.max_results = max_results

    def fetch(self) -> list[Email]:
        users = self.service.users()
        listing = users.messages().list(
            userId="me", q=f"label:{self.label}", maxResults=self.max_results).execute()
        emails = []
        for ref in listing.get("messages", []):
            msg = users.messages().get(userId="me", id=ref["id"], format="raw").execute()
            emails.append(parse_raw(base64.urlsafe_b64decode(msg["raw"]), source_id=ref["id"]))
        emails.sort(key=lambda e: e.date)
        return emails

    def add_tags(self, source_id: str, tags: list[str]) -> None:
        """Read-only scope: labels stay inside the agent's own database for Gmail."""
        return None
