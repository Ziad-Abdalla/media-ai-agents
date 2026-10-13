"""Where emails come from. Two sources with the same method: fetch() -> list[Email].

MailpitInbox reads the local test mail server. GmailInbox reads a real Gmail
label with a read-only permission. The rest of the agent doesn't care which one.
"""

import base64
import os
from email.utils import parseaddr

import httpx

from . import config
from .models import Email


class MailpitInbox:
    def __init__(self, base_url: str = config.MAILPIT_URL):
        self.base_url = base_url.rstrip("/")

    def fetch(self) -> list[Email]:
        listing = httpx.get(f"{self.base_url}/api/v1/messages", timeout=10).json()
        emails = []
        for summary in reversed(listing.get("messages", [])):  # oldest first
            msg = httpx.get(f"{self.base_url}/api/v1/message/{summary['ID']}", timeout=10).json()
            emails.append(Email(
                message_id=msg["MessageID"],
                sender=msg["From"]["Address"].lower(),
                subject=msg.get("Subject", ""),
                body=msg.get("Text", ""),
                received_at=msg.get("Date", ""),
            ))
        return emails


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
    def __init__(self, service, label: str = config.GMAIL_LABEL, max_results: int = 20):
        self.service = service
        self.label = label
        self.max_results = max_results

    def fetch(self) -> list[Email]:
        users = self.service.users()
        listing = users.messages().list(
            userId="me", q=f"label:{self.label}", maxResults=self.max_results).execute()
        emails = []
        for ref in listing.get("messages", []):
            msg = users.messages().get(userId="me", id=ref["id"], format="full").execute()
            emails.append(parse_gmail_message(msg))
        return emails


def parse_gmail_message(msg: dict) -> Email:
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return Email(
        message_id=headers.get("message-id", msg["id"]),
        sender=parseaddr(headers.get("from", ""))[1].lower(),
        subject=headers.get("subject", ""),
        body=_plain_text(msg["payload"]),
        received_at=headers.get("date", ""),
    )


def _plain_text(part: dict) -> str:
    """Find the text/plain part. Emails can nest parts inside parts, so we look recursively."""
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    for child in part.get("parts", []):
        text = _plain_text(child)
        if text:
            return text
    return ""
