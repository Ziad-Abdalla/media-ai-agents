"""Step 5c (Q44): what the agent is allowed to do, enforced in code (not only in the prompt).

Every action goes through execute(). It looks the action up in ALLOWED_ACTIONS and:
  auto       runs it (reading, labelling, drafting: nothing leaves the agent's own records,
             except the morning briefing, which DLP pins to one internal address)
  approval   runs only with a named approver who has that right in the staff directory,
             only if the kill switch is off, and only if the email isn't quarantined
  forbidden  refused and logged, even with approval. Any action not in the table is forbidden.
Anything that sends a message also passes the DLP check (dlp.py) right before it goes.

The model never calls this. The model only fills in a JSON form (models.Classification);
the pipeline code decides which actions to propose.
"""

from . import config
from .actions import HANDLERS, ForbiddenAction
from .dlp import check_outbound

AUTO, APPROVAL, FORBIDDEN = "auto", "approval", "forbidden"

ALLOWED_ACTIONS = {
    # automatic: inside the agent's own records
    "apply_label": AUTO,
    "draft_reply": AUTO,
    "send_briefing": AUTO,          # DLP: only to the executive office address
    # a named person must approve the exact plan
    "send_reply": APPROVAL,         # DLP: only to people already in the conversation, allowed domains
    "forward_internal": APPROVAL,   # DLP: company addresses only
    "create_task": APPROVAL,        # task on the board / Odoo Project
    "reassign_task": APPROVAL,
    "release_quarantine": APPROVAL, # only IT security or the CEO
    # never, even with approval
    "send_external": FORBIDDEN,     # anything to a domain outside the allow-list
    "attach_files": FORBIDDEN,
    "bulk_export": FORBIDDEN,
    "delete_email": FORBIDDEN,
}
SENDS_MAIL = {"send_reply", "forward_internal", "send_briefing"}
BLOCKED_WHEN_QUARANTINED = {"send_reply", "forward_internal", "create_task", "reassign_task"}


class ApprovalRequired(Exception):
    pass


class NotAuthorized(Exception):
    pass


class WritesDisabled(Exception):
    pass


class DLPBlocked(Exception):
    pass


def execute(action: str, plan: dict, *, ctx, approved_by: str | None = None):
    """Run one action if the rules allow it. Returns the handler's result. Raises otherwise."""
    rule = ALLOWED_ACTIONS.get(action, FORBIDDEN)
    actor = f"agent, approved by {approved_by}" if approved_by else "agent"
    ids = {"email_id": plan.get("email_id"), "task_id": plan.get("task_id"),
           "action_id": plan.get("action_id")}

    def refuse(exc_type, why):
        ctx.store.audit(actor, f"blocked:{action}", outcome="blocked", detail={"why": why, "plan": plan},
                        **ids)
        raise exc_type(why)

    if rule == FORBIDDEN:
        refuse(ForbiddenAction, f"'{action}' is forbidden for this agent")

    if rule == APPROVAL:
        if not approved_by:
            raise ApprovalRequired(f"'{action}' needs a named person's approval")
        if not ctx.directory.can_approve(approved_by, _right(action)):
            refuse(NotAuthorized, f"{approved_by} may not approve '{action}'")
        if not config.writes_enabled():
            refuse(WritesDisabled, "kill switch is on: nothing is sent or written")
        if action in BLOCKED_WHEN_QUARANTINED and plan.get("email_id"):
            email = ctx.store.get_email(plan["email_id"])
            if email and email["status"] == "quarantined":
                refuse(ForbiddenAction, "email is quarantined (possible injection)")

    if action in SENDS_MAIL:
        if action == "send_briefing" and not config.writes_enabled():
            refuse(WritesDisabled, "kill switch is on: nothing is sent or written")
        dlp = check_outbound(action, to=plan.get("to", []), cc=plan.get("cc"),
                             body=plan.get("body") or plan.get("text", ""),
                             attachments=plan.get("attachments"), directory=ctx.directory,
                             conversation=plan.get("conversation"))
        if dlp.blocked:
            refuse(DLPBlocked, "; ".join(dlp.reasons))

    result = HANDLERS[action](ctx, plan)
    ctx.store.audit(actor, action, outcome="ok", detail={"plan": plan, "result": result}, **ids)
    return result


def _right(action: str) -> str:
    """Which right in staff.yaml (can_approve) an action needs."""
    return "create_task" if action == "reassign_task" else action
