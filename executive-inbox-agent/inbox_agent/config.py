"""All settings in one place, read from environment variables (or a .env file)."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

ROOT = Path(__file__).resolve().parent.parent

MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")

MAILPIT_URL = os.environ.get("MAILPIT_URL", "http://localhost:8027")
SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1027"))

AGENT_DB_PATH = os.environ.get("AGENT_DB_PATH", str(ROOT / "inbox_agent.sqlite"))
STAFF_FILE = os.environ.get("STAFF_FILE", str(ROOT / "data" / "staff.yaml"))
DATASET_FILE = os.environ.get("DATASET_FILE", str(ROOT / "data" / "emails.yaml"))
GOLD_FILE = os.environ.get("GOLD_FILE", str(ROOT / "data" / "gold.yaml"))
KILL_SWITCH_FILE = os.environ.get("KILL_SWITCH_FILE", str(ROOT / "agent.kill"))

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
THREAD_SIMILARITY_THRESHOLD = float(os.environ.get("THREAD_SIMILARITY_THRESHOLD", "0.88"))
THREAD_WINDOW_DAYS = int(os.environ.get("THREAD_WINDOW_DAYS", "30"))

MAX_CORRECTION_EXAMPLES = int(os.environ.get("MAX_CORRECTION_EXAMPLES", "6"))
MANUAL_TRIAGE_MINUTES = float(os.environ.get("MANUAL_TRIAGE_MINUTES", "3"))
GMAIL_LABEL = os.environ.get("GMAIL_LABEL", "ceo-office")


def writes_enabled() -> bool:
    """The kill switch, checked before every action that sends or writes outside the agent.
    Creating the agent.kill file stops everything at once, no restart needed."""
    if os.environ.get("AGENT_WRITES_ENABLED", "true").lower() == "false":
        return False
    return not os.path.exists(KILL_SWITCH_FILE)
