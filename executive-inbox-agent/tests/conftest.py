"""Test helpers: a fake Anthropic client, a fake embedder, a throw-away database.
Unit tests never touch the network and never spend money."""

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from inbox_agent import config
from inbox_agent.actions import LocalBoard
from inbox_agent.directory import Directory
from inbox_agent.evaluate import RecordingMailer
from inbox_agent.inbox import build_mime, parse_raw
from inbox_agent.normalize import normalize_ar
from inbox_agent.pipeline import Context
from inbox_agent.store import Store
from inbox_agent.threads import ThreadLinker


def classification(**over):
    base = {"category": "urgent_action", "priority": "high", "language": "ar", "dialect": "msa",
            "summary_ar": "ملخص تجريبي.", "tasks": [], "needs_reply": False, "reply_draft": None,
            "suspicious_instructions": False, "suspicious_reason": None}
    base.update(over)
    return base


def task(**over):
    base = {"what_ar": "متابعة التصريح", "deadline": "2026-10-14", "urgent": False,
            "suggested_owner_id": "abdulrahman", "owner_reason": "permits", "owner_confidence": "high",
            "evidence_quote": "تصريح التصوير"}
    base.update(over)
    return base


class FakeAnthropic:
    """Returns a canned classification. `reply` can be a dict or a function(user_message) -> dict.
    Remembers every request so tests can inspect what was sent."""

    def __init__(self, reply=None, stop_reason="end_turn"):
        self.reply = reply if reply is not None else classification()
        self.stop_reason = stop_reason
        self.sent = []
        self.messages = self

    def create(self, **kwargs):
        self.sent.append(kwargs)
        data = self.reply(kwargs["messages"][0]["content"]) if callable(self.reply) else self.reply
        return SimpleNamespace(
            model=kwargs["model"], stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=1500, output_tokens=300,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0),
            content=[SimpleNamespace(type="thinking", thinking="..."),
                     SimpleNamespace(type="text", text=json.dumps(data, ensure_ascii=False))])


class FakeEmbedder:
    """Bag of words hashed into 256 numbers: texts sharing words get similar vectors."""

    def encode(self, texts):
        out = []
        for t in texts:
            v = np.zeros(256, dtype=np.float32)
            for w in normalize_ar(t).split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return np.array(out, dtype=np.float32)


def make_email(id="x1", body="نرجو متابعة تصريح التصوير في حي الطريف.", subject="تصريح التصوير",
               sender=("Muni", "permits@riyadh-municipality.example"), date="2026-10-12T09:00:00+03:00",
               message_id=None, in_reply_to=None, references=None, attachments=None, html_hidden=None,
               to=None, cc=None):
    item = {"id": id, "from": {"name": sender[0], "email": sender[1]},
            "to": to or ["ceo-office@sadaf.example"], "cc": cc or [], "date": date, "subject": subject,
            "message_id": message_id or f"<{id}@test.example>", "in_reply_to": in_reply_to,
            "references": references or [], "body": body, "html_hidden": html_hidden,
            "attachments": attachments or []}
    return parse_raw(build_mime(item).as_bytes(), source_id=id)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own cost ledger, kill switch file and settings."""
    monkeypatch.setenv("COST_DB_PATH", str(tmp_path / "costs.sqlite"))
    monkeypatch.setenv("COST_BUDGET_USD", "15")
    monkeypatch.setenv("AGENT_WRITES_ENABLED", "true")
    monkeypatch.setattr(config, "KILL_SWITCH_FILE", str(tmp_path / "agent.kill"))


@pytest.fixture
def directory():
    return Directory()


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "agent.sqlite"))


@pytest.fixture
def ctx(store, directory):
    linker = ThreadLinker(store, FakeEmbedder(), threshold=0.6,
                          ignore_addresses=["ceo-office@sadaf.example", "inbox-agent@sadaf.example"])
    return Context(store=store, directory=directory, linker=linker, mailer=RecordingMailer(),
                   board=LocalBoard(store), batch="test")
