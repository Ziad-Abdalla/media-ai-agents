"""Local SQLite storage: the `runs` table (one row per email) and the `audit` table
(one row per write to Odoo, with before and after values so we can undo it)."""

import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    sender TEXT, subject TEXT, body TEXT, received_at TEXT,
    idempotency_key TEXT UNIQUE,      -- hash of message-id + the request; one PO per key
    fingerprint TEXT,                 -- hash of the request only; spots re-sent duplicates
    status TEXT NOT NULL,
    request_json TEXT,                -- what the model extracted
    problems_json TEXT,               -- what validation found missing
    resolution_json TEXT,             -- which Odoo records we matched
    plan_json TEXT,                   -- the exact writes we will make if approved
    reply_draft TEXT,
    duplicate_of TEXT,
    po_id INTEGER,
    error TEXT,
    approved_by TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    actor TEXT NOT NULL,              -- "agent" or "human:<name>"
    operation TEXT NOT NULL,          -- create / write / rollback_* / blocked:<action>
    model TEXT,
    record_id INTEGER,
    before_json TEXT,
    after_json TEXT
);
"""

JSON_COLUMNS = ("request_json", "problems_json", "resolution_json", "plan_json")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = config.AGENT_DB_PATH):
        # The web server answers requests on several threads, and they share this one
        # connection, so every method takes the lock first: one database call at a time.
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ---- runs ----
    def add_run(self, **fields) -> None:
        fields = self._encode(fields)
        fields["created_at"] = fields["updated_at"] = now()
        cols = ", ".join(fields)
        with self.lock:
            self.conn.execute(f"INSERT INTO runs ({cols}) VALUES ({', '.join('?' * len(fields))})",
                              list(fields.values()))
            self.conn.commit()

    def update_run(self, run_id: str, **fields) -> None:
        fields = self._encode(fields)
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE runs SET {sets} WHERE run_id = ?", [*fields.values(), run_id])
            self.conn.commit()

    def claim_for_writing(self, run_id: str, approver: str) -> bool:
        """Move a run to 'writing' in ONE database step, only if it is waiting for approval.
        If two people click Approve at the same moment, only one gets True."""
        with self.lock:
            cur = self.conn.execute(
                "UPDATE runs SET status = 'writing', approved_by = ?, updated_at = ?"
                " WHERE run_id = ? AND status IN ('pending_approval', 'write_failed')",
                (approver, now(), run_id))
            self.conn.commit()
        return cur.rowcount == 1

    def get_run(self, run_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._decode(row) if row else None

    def find_run(self, **where) -> dict | None:
        conds = " AND ".join(f"{k} = ?" for k in where)
        with self.lock:
            row = self.conn.execute(f"SELECT * FROM runs WHERE {conds} ORDER BY created_at LIMIT 1",
                                    list(where.values())).fetchone()
        return self._decode(row) if row else None

    def list_runs(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [self._decode(r) for r in rows]

    # ---- audit ----
    def audit(self, run_id, actor, operation, model=None, record_id=None, before=None, after=None):
        with self.lock:
            self.conn.execute(
                "INSERT INTO audit (ts, run_id, actor, operation, model, record_id, before_json, after_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now(), run_id, actor, operation, model, record_id,
                 json.dumps(before, default=str) if before is not None else None,
                 json.dumps(after, default=str) if after is not None else None))
            self.conn.commit()

    def audit_rows(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM audit WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["before"] = json.loads(d.pop("before_json")) if r["before_json"] else None
            d["after"] = json.loads(d.pop("after_json")) if r["after_json"] else None
            out.append(d)
        return out

    # ---- helpers ----
    @staticmethod
    def _encode(fields: dict) -> dict:
        return {k: (json.dumps(v, default=str) if k in JSON_COLUMNS and v is not None else v)
                for k, v in fields.items()}

    @staticmethod
    def _decode(row) -> dict:
        d = dict(row)
        for k in JSON_COLUMNS:
            if d.get(k):
                d[k] = json.loads(d[k])
        return d
