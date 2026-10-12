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
from .actions import GATE, HANDLERS, ForbiddenAction
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
    "rollback_action": APPROVAL,    # undo a task creation / reassignment
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
    """Run one action if the rules allow it. Returns the handler's result. Raises otherwise.

    Every check fails CLOSED: if a check itself errors (bad plan, directory problem, DLP crash,
    unknown email), the action is refused and audited, never run."""
    rule = ALLOWED_ACTIONS.get(action, FORBIDDEN)
    if action not in HANDLERS and rule != FORBIDDEN:
        rule = FORBIDDEN  # a rule without code behind it is a mistake: refuse
    actor = f"agent, approved by {approved_by}" if approved_by else "agent"
    plan = plan if isinstance(plan, dict) else {}
    ids = {"email_id": plan.get("email_id"), "task_id": plan.get("task_id"),
           "action_id": plan.get("action_id")}

    def refuse(exc_type, why):
        ctx.store.audit(actor, f"blocked:{action}", outcome="blocked", detail={"why": why, "plan": plan},
                        **ids)
        raise exc_type(why)

    try:
        _check(action, rule, plan, ctx, approved_by)
    except _Refusal as r:
        refuse(r.exc_type, r.why)
    except Exception as e:  # a check that crashes is a check that failed
        refuse(ForbiddenAction, f"safety check failed ({type(e).__name__}: {e}); refused")

    token = GATE.set(action)
    try:
        result = HANDLERS[action](ctx, plan)
    finally:
        GATE.reset(token)
    ctx.store.audit(actor, action, outcome="ok", detail={"plan": plan, "result": result}, **ids)
    return result


class _Refusal(Exception):
    def __init__(self, exc_type, why):
        super().__init__(why)
        self.exc_type, self.why = exc_type, why


def _check(action, rule, plan, ctx, approved_by) -> None:
    if rule == FORBIDDEN:
        raise _Refusal(ForbiddenAction, f"'{action}' is forbidden for this agent")

    if rule == APPROVAL:
        if not approved_by:
            raise _Refusal(ApprovalRequired, f"'{action}' needs a named person's approval")
        if not ctx.directory.can_approve(approved_by, _right(action)):
            raise _Refusal(NotAuthorized, f"{approved_by} may not approve '{action}'")
        if not config.writes_enabled():
            raise _Refusal(WritesDisabled, "kill switch is on: nothing is sent or written")
        if action in BLOCKED_WHEN_QUARANTINED:
            # the email must exist and be in a state a person cleared; anything else is refused
            email = ctx.store.get_email(plan.get("email_id") or "")
            if not email:
                raise _Refusal(ForbiddenAction, "no known email for this action")
            if email["status"] not in ("triaged", "released"):
                raise _Refusal(ForbiddenAction, f"email status is '{email['status']}' "
                                                "(quarantined or not triaged): no actions on it")

    if action in SENDS_MAIL:
        if not config.writes_enabled():
            raise _Refusal(WritesDisabled, "kill switch is on: nothing is sent or written")
        dlp = check_outbound(action, to=plan.get("to") or [], cc=plan.get("cc"),
                             body=plan.get("body") or plan.get("text", ""),
                             attachments=plan.get("attachments"), directory=ctx.directory,
                             conversation=plan.get("conversation"))
        if dlp.blocked:
            raise _Refusal(DLPBlocked, "; ".join(dlp.reasons))


def _right(action: str) -> str:
    """Which right in staff.yaml (can_approve) an action needs."""
    return "create_task" if action in ("reassign_task", "rollback_action") else action
