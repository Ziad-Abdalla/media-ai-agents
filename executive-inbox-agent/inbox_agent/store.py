"""Local SQLite storage.

  emails       one row per email: parsed text, thread link, guard result, classification
  threads      one row per conversation
  tasks        tasks extracted from emails, with proposed owner, evidence and review state
  actions      every action that needs a person (send reply, create task...), with the exact
               plan that will run; approval is bound to that plan's hash
  corrections  every time a person changed the owner the agent proposed (Q43 feedback loop)
  audit        one row per thing the agent or a person did, including blocked attempts
  board_tasks  the local task board (stands in for Odoo Project when Odoo isn't connected)
"""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    source_id TEXT,
    thread_id TEXT,
    from_addr TEXT, from_name TEXT, to_json TEXT, cc_json TEXT,
    subject TEXT, date TEXT,
    new_text TEXT, quoted_text TEXT, forwarded_json TEXT, attachments_json TEXT,
    in_reply_to TEXT, references_json TEXT,
    embedding BLOB,
    link_json TEXT,              -- how it was linked to a thread: method, confidence, reason
    guard_json TEXT,             -- injection detector result
    classification_json TEXT,    -- what the model returned
    category TEXT, priority TEXT, language TEXT, summary_ar TEXT,
    status TEXT NOT NULL,        -- triaged / quarantined / released / error
    labels_json TEXT,
    run_id TEXT, error TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    subject_norm TEXT,
    subject TEXT,
    participants_json TEXT,
    first_date TEXT, last_date TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    what_ar TEXT, deadline TEXT, urgent INTEGER,
    evidence_quote TEXT, evidence_found INTEGER,
    model_owner TEXT, model_reason TEXT, model_confidence TEXT,
    rule_owner TEXT, rule_reason TEXT,
    proposed_owner TEXT, owner_note TEXT,
    needs_confirmation INTEGER, confirm_reasons_json TEXT,
    status TEXT NOT NULL,        -- proposed / needs_confirmation / confirmed / reassigned / rejected
    final_owner TEXT, decided_by TEXT, decided_at TEXT,
    board_task_id INTEGER
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT, task_id INTEGER,
    kind TEXT NOT NULL,          -- send_reply / forward_internal / create_task / release_quarantine
    plan_json TEXT NOT NULL,     -- exactly what will run if approved
    status TEXT NOT NULL,        -- pending / executing / executed / rejected / blocked / failed / rolled_back
    dlp_json TEXT,
    approved_by TEXT, result_json TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER, email_id TEXT,
    task_text TEXT, subject TEXT, evidence_quote TEXT,
    from_owner TEXT, to_owner TEXT, reason TEXT,
    corrected_by TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,         -- "agent" / "agent, approved by <id>" / "human:<id>"
    action TEXT NOT NULL,        -- e.g. classify, apply_label, blocked:send_external
    email_id TEXT, task_id INTEGER, action_id INTEGER,
    outcome TEXT,                -- ok / blocked / failed
    detail_json TEXT
);
CREATE TABLE IF NOT EXISTS board_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, description TEXT, user_id TEXT, deadline TEXT,
    active INTEGER DEFAULT 1, origin TEXT, created_at TEXT
);
"""

JSON_COLUMNS = {"to_json", "cc_json", "forwarded_json", "attachments_json", "references_json",
                "link_json", "guard_json", "classification_json", "labels_json",
                "confirm_reasons_json", "plan_json", "dlp_json", "result_json", "participants_json",
                "detail_json"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def plan_hash(plan) -> str:
    """Hash of the exact plan. The page shows it and sends it back with the click, so Approve
    only runs the plan the person actually saw. Any change to the plan changes the hash."""
    canonical = json.dumps(plan, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def email_key(message_id: str) -> str:
    return "E-" + hashlib.sha256(message_id.encode()).hexdigest()[:10]


class Store:
    def __init__(self, path: str = config.AGENT_DB_PATH):
        # The web server answers on several threads that share this connection,
        # so every method takes the lock first: one database call at a time.
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("plan_hash", 1, lambda t: plan_hash(json.loads(t or "null")))
        self.conn.executescript(SCHEMA)

    # ---- generic helpers ----
    @staticmethod
    def _encode(fields: dict) -> dict:
        return {k: (json.dumps(v, ensure_ascii=False, default=str)
                    if k in JSON_COLUMNS and v is not None else v) for k, v in fields.items()}

    @staticmethod
    def _decode(row) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k in JSON_COLUMNS & d.keys():
            if d[k]:
                d[k] = json.loads(d[k])
        return d

    def _insert(self, table: str, fields: dict) -> int:
        fields = self._encode(fields)
        cols = ", ".join(fields)
        with self.lock:
            cur = self.conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(fields))})",
                list(fields.values()))
            self.conn.commit()
            return cur.lastrowid

    def _update(self, table: str, key: str, value, fields: dict) -> None:
        fields = self._encode(fields)
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", [*fields.values(), value])
            self.conn.commit()

    def query(self, sql: str, params=()) -> list[dict]:
        with self.lock:
            return [self._decode(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---- emails & threads ----
    def add_email(self, **fields) -> None:
        fields.setdefault("created_at", now())
        self._insert("emails", fields)

    def update_email(self, email_id: str, **fields) -> None:
        self._update("emails", "id", email_id, fields)

    def get_email(self, email_id: str) -> dict | None:
        return self.one("SELECT * FROM emails WHERE id = ?", (email_id,))

    def email_by_message_id(self, message_id: str) -> dict | None:
        return self.one("SELECT * FROM emails WHERE message_id = ?", (message_id,))

    def emails(self, where: str = "1=1", params=()) -> list[dict]:
        return self.query(f"SELECT * FROM emails WHERE {where} ORDER BY date", params)

    def add_thread(self, **fields) -> None:
        self._insert("threads", fields)

    def update_thread(self, thread_id: str, **fields) -> None:
        self._update("threads", "id", thread_id, fields)

    def get_thread(self, thread_id: str) -> dict | None:
        return self.one("SELECT * FROM threads WHERE id = ?", (thread_id,))

    def threads(self) -> list[dict]:
        return self.query("SELECT * FROM threads ORDER BY last_date DESC")

    # ---- tasks ----
    def add_task(self, **fields) -> int:
        return self._insert("tasks", fields)

    def update_task(self, task_id: int, **fields) -> None:
        self._update("tasks", "id", task_id, fields)

    def get_task(self, task_id: int) -> dict | None:
        return self.one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def tasks(self, where: str = "1=1", params=()) -> list[dict]:
        return self.query(f"SELECT * FROM tasks WHERE {where} ORDER BY id", params)

    # ---- actions ----
    def add_action(self, **fields) -> int:
        fields.setdefault("created_at", now())
        fields.setdefault("updated_at", fields["created_at"])
        return self._insert("actions", fields)

    def update_action(self, action_id: int, **fields) -> None:
        fields["updated_at"] = now()
        self._update("actions", "id", action_id, fields)

    def get_action(self, action_id: int) -> dict | None:
        return self.one("SELECT * FROM actions WHERE id = ?", (action_id,))

    def actions(self, where: str = "1=1", params=()) -> list[dict]:
        return self.query(f"SELECT * FROM actions WHERE {where} ORDER BY id", params)

    def claim_action(self, action_id: int, approver: str, shown_plan_hash: str) -> bool:
        """Move an action from 'pending' to 'executing' in ONE database step, only if its
        plan is still the one the approver saw. If two people click at once, one wins."""
        with self.lock:
            cur = self.conn.execute(
                "UPDATE actions SET status = 'executing', approved_by = ?, updated_at = ?"
                " WHERE id = ? AND status = 'pending' AND plan_hash(plan_json) = ?",
                (approver, now(), action_id, shown_plan_hash))
            self.conn.commit()
        return cur.rowcount == 1

    # ---- corrections ----
    def add_correction(self, **fields) -> int:
        fields.setdefault("ts", now())
        return self._insert("corrections", fields)

    def corrections(self, limit: int | None = None) -> list[dict]:
        sql = "SELECT * FROM corrections ORDER BY id DESC"
        return self.query(sql + (f" LIMIT {int(limit)}" if limit else ""))

    # ---- audit ----
    def audit(self, actor: str, action: str, *, email_id=None, task_id=None, action_id=None,
              outcome: str = "ok", detail=None) -> None:
        self._insert("audit", {"ts": now(), "actor": actor, "action": action, "email_id": email_id,
                               "task_id": task_id, "action_id": action_id, "outcome": outcome,
                               "detail_json": detail})

    def audit_rows(self, where: str = "1=1", params=(), limit: int = 500) -> list[dict]:
        return self.query(f"SELECT * FROM audit WHERE {where} ORDER BY id DESC LIMIT {int(limit)}",
                          params)
