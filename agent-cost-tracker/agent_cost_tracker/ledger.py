"""The ledger: one SQLite table with one row per API call."""

import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                 -- UTC time, ISO format
    operation TEXT NOT NULL,          -- e.g. "extract_purchase_request"
    run_id TEXT,                      -- groups the calls of one agent run
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_creation_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    stop_reason TEXT
)
"""


def db_path() -> str:
    return os.environ.get("COST_DB_PATH", "./costs.sqlite")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def record_call(conn: sqlite3.Connection, **row) -> None:
    row.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO calls ({columns}) VALUES ({placeholders})", list(row.values()))
    conn.commit()


def total_spend(conn: sqlite3.Connection, operation: str | None = None) -> float:
    if operation is None:
        result = conn.execute("SELECT SUM(cost_usd) FROM calls").fetchone()[0]
    else:
        result = conn.execute(
            "SELECT SUM(cost_usd) FROM calls WHERE operation = ?", (operation,)
        ).fetchone()[0]
    return result or 0.0


def run_spend(conn: sqlite3.Connection, run_id: str) -> float:
    result = conn.execute("SELECT SUM(cost_usd) FROM calls WHERE run_id = ?", (run_id,)).fetchone()[0]
    return result or 0.0
