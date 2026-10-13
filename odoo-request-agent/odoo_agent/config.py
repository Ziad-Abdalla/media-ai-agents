"""All settings in one place, read from environment variables (or a .env file)."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))


def _list(name: str, default: str) -> list[str]:
    return [x.strip().lower() for x in os.environ.get(name, default).split(",") if x.strip()]


MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")

ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.environ.get("ODOO_DB", "sadaf_demo")
ODOO_USER = os.environ.get("ODOO_USER", "admin")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD", "admin")

MAILPIT_URL = os.environ.get("MAILPIT_URL", "http://localhost:8025")
SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
AGENT_EMAIL = os.environ.get("AGENT_EMAIL", "procurement-agent@sadaf.example")

# Used both to accept senders and to limit who the agent may email.
COMPANY_DOMAINS = _list("COMPANY_DOMAINS", "sadaf.example")
ALLOWED_CURRENCIES = [c.upper() for c in _list("ALLOWED_CURRENCIES", "SAR,USD")]

AGENT_DB_PATH = os.environ.get("AGENT_DB_PATH", "./agent.sqlite")
KILL_SWITCH_FILE = os.environ.get("KILL_SWITCH_FILE", "./agent.kill")
GMAIL_LABEL = os.environ.get("GMAIL_LABEL", "purchase-requests")

# Productions are Odoo analytic accounts under this analytic plan; every PO line is charged to one.
PRODUCTION_PLAN = os.environ.get("PRODUCTION_PLAN", "Productions")
# Budget per production, by analytic account code (Odoo Community has no budget module).
BUDGETS_FILE = os.environ.get("BUDGETS_FILE",
                              str(Path(__file__).resolve().parent.parent / "production_budgets.json"))

# KPI report: the time-saved estimate is only as good as these assumptions, so they are settings.
MINUTES_MANUAL_PO = float(os.environ.get("MINUTES_MANUAL_PO", "12"))   # by hand: read, look up, key in Odoo
MINUTES_REVIEW_PO = float(os.environ.get("MINUTES_REVIEW_PO", "2"))    # check the agent's plan, click Approve
MINUTES_PER_REPLY = float(os.environ.get("MINUTES_PER_REPLY", "3"))    # writing a "please send X" reply


def writes_enabled() -> bool:
    """The kill switch, checked before every write. The agent.kill file works instantly.
    AGENT_WRITES_ENABLED comes from the environment (.env is read once at start-up), so
    changing that one needs a restart."""
    if os.environ.get("AGENT_WRITES_ENABLED", "true").lower() == "false":
        return False
    return not os.path.exists(KILL_SWITCH_FILE)
