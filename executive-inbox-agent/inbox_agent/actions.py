"""The things the agent can actually do. Nothing here is called directly: everything goes
through permissions.execute(), which decides whether it may run at all.

Also the two "outside world" adapters:
  Mailer      sends through SMTP. In this project SMTP is Mailpit, so nothing reaches the internet.
  LocalBoard  a task board in our own SQLite file, the stand-in for Odoo Project.
  OdooBoard   the same three methods on a real Odoo (project.task over XML-RPC).
"""

import contextvars
import functools
import smtplib
import xmlrpc.client
from email.message import EmailMessage
from email.utils import make_msgid

from . import config
from .store import now


class ForbiddenAction(Exception):
    pass


# ---------------------------------------------------------------- adapters
class Mailer:
    def __init__(self, host: str = config.SMTP_HOST, port: int = config.SMTP_PORT):
        self.host, self.port = host, port

    def send(self, msg: EmailMessage) -> str:
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.send_message(msg)
        return msg["Message-ID"]


class LocalBoard:
    """Task board in the agent's own database (table board_tasks)."""

    def __init__(self, store):
        self.store = store

    def create(self, values: dict) -> int:
        row = {k: values.get(k) for k in ("name", "description", "user_id", "deadline", "origin")}
        return self.store._insert("board_tasks", {**row, "active": 1, "created_at": now()})

    def read(self, task_id: int) -> dict | None:
        return self.store.one("SELECT * FROM board_tasks WHERE id = ?", (task_id,))

    def write(self, task_id: int, values: dict) -> None:
        known = {k: v for k, v in values.items() if k in ("name", "description", "user_id", "deadline", "active")}
        self.store._update("board_tasks", "id", task_id, known)


class OdooBoard:
    """project.task in Odoo. user_id is mapped to an Odoo user by email (login)."""

    def __init__(self, url: str, db: str, user: str, password: str, project_id: int):
        self.db, self.password, self.project_id = db, password, project_id
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        self.uid = common.authenticate(db, user, password, {})
        self.models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def _call(self, model, method, *args, **kw):
        return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kw)

    def _odoo_user(self, login: str) -> list[int]:
        ids = self._call("res.users", "search", [["login", "=", login]])
        return ids[:1]

    def create(self, values: dict) -> int:
        return self._call("project.task", "create", {
            "name": values["name"], "description": values.get("description", ""),
            "project_id": self.project_id, "date_deadline": values.get("deadline") or False,
            "user_ids": [(6, 0, self._odoo_user(values["user_email"]))]})

    def read(self, task_id: int) -> dict | None:
        rows = self._call("project.task", "read", [task_id], fields=["name", "user_ids", "active"])
        return rows[0] if rows else None

    def write(self, task_id: int, values: dict) -> None:
        odoo_values = {}
        if "user_email" in values:
            odoo_values["user_ids"] = [(6, 0, self._odoo_user(values["user_email"]))]
        if "active" in values:
            odoo_values["active"] = bool(values["active"])
        self._call("project.task", "write", [task_id], odoo_values)


# ---------------------------------------------------------------- message building
def _message(ctx, to, subject, body, in_reply_to=None, references=None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"Executive Inbox Agent <{ctx.directory.company['agent_address']}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=ctx.directory.company_domains[0])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = " ".join([*(references or []), in_reply_to])
    msg.set_content(body)
    return msg


# ---------------------------------------------------------------- the gate token
# permissions.execute() sets this to the action's name just before it calls the handler.
# A handler called any other way (a shortcut in new code, a test, a script) finds no token,
# refuses, and writes a "blocked:ungated" row in the audit log. One door in, no side doors.
GATE = contextvars.ContextVar("inbox_agent_gate", default=None)


def gated(fn):
    @functools.wraps(fn)
    def wrapper(ctx, plan):
        if GATE.get() != fn.__name__:
            ctx.store.audit("agent", f"blocked:ungated:{fn.__name__}", outcome="blocked",
                            email_id=plan.get("email_id"), task_id=plan.get("task_id"),
                            detail={"why": "handler called without going through permissions.execute"})
            raise ForbiddenAction(f"'{fn.__name__}' must go through permissions.execute()")
        return fn(ctx, plan)
    return wrapper


# ---------------------------------------------------------------- handlers
# Each handler gets the context and the plan, and returns a small dict for the audit log.

@gated
def apply_label(ctx, plan):
    email = ctx.store.get_email(plan["email_id"])
    labels = sorted(set((email.get("labels_json") or []) + plan["labels"]))
    ctx.store.update_email(plan["email_id"], labels_json=labels)
    if ctx.inbox is not None and hasattr(ctx.inbox, "add_tags") and email.get("source_id"):
        try:
            ctx.inbox.add_tags(email["source_id"], labels)
        except Exception as e:  # a label that didn't reach Mailpit is not worth failing over
            return {"labels": labels, "mailbox_tag_error": str(e)}
    return {"labels": labels}


@gated
def draft_reply(ctx, plan):
    # A draft only lives in our database. Sending it is a separate action that needs approval.
    return {"saved": True, "chars": len(plan["body"])}


@gated
def send_reply(ctx, plan):
    msg = _message(ctx, plan["to"], plan["subject"], plan["body"],
                   plan.get("in_reply_to"), plan.get("references"))
    return {"message_id": ctx.mailer.send(msg), "to": plan["to"]}


@gated
def forward_internal(ctx, plan):
    msg = _message(ctx, plan["to"], plan["subject"], plan["body"])
    return {"message_id": ctx.mailer.send(msg), "to": plan["to"]}


@gated
def send_briefing(ctx, plan):
    msg = _message(ctx, plan["to"], plan["subject"], plan["text"])
    msg.add_alternative(plan["html"], subtype="html")
    return {"message_id": ctx.mailer.send(msg), "to": plan["to"]}


@gated
def create_task(ctx, plan):
    owner = ctx.directory.get(plan["owner"])
    board_id = ctx.board.create({"name": plan["name"], "description": plan["description"],
                                 "user_id": owner.id, "user_email": owner.email,
                                 "deadline": plan.get("deadline"), "origin": plan["email_id"]})
    ctx.store.update_task(plan["task_id"], board_task_id=board_id)
    return {"board_task_id": board_id, "owner": owner.id}


@gated
def reassign_task(ctx, plan):
    owner = ctx.directory.get(plan["new_owner"])
    before = ctx.board.read(plan["board_task_id"])
    ctx.board.write(plan["board_task_id"], {"user_id": owner.id, "user_email": owner.email})
    return {"board_task_id": plan["board_task_id"], "before": before and before.get("user_id"),
            "after": owner.id}


@gated
def release_quarantine(ctx, plan):
    ctx.store.update_email(plan["email_id"], status="released")
    return {"released": plan["email_id"]}


@gated
def rollback_action(ctx, plan):
    """Undo an executed create_task (archive it) or reassign_task (restore the old owner)."""
    if plan["kind"] == "create_task":
        ctx.board.write(plan["board_task_id"], {"active": 0})
        return {"archived_board_task": plan["board_task_id"]}
    if plan["kind"] == "reassign_task":
        old = ctx.directory.get(plan["old_owner"])
        ctx.board.write(plan["board_task_id"], {"user_id": old.id, "user_email": old.email})
        return {"owner_restored": old.id}
    raise ForbiddenAction(f"{plan['kind']} can't be rolled back automatically (email already sent)")


HANDLERS = {f.__name__: f for f in (apply_label, draft_reply, send_reply, forward_internal,
                                    send_briefing, create_task, reassign_task, release_quarantine,
                                    rollback_action)}
