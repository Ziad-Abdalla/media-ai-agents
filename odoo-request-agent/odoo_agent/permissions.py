"""Step 8: what the agent is allowed to do, enforced in code (not just in the prompt).

Every write and every email goes through execute(). (Reads go straight to Odoo, because
they can't change anything; rollback is a human tool and also sits outside this gate.) It looks the action up in
ALLOWED_ACTIONS and:
  - "auto":     runs it.
  - "approval": runs it only if a human approved, and only if the kill switch is off.
  - "forbidden" (or any action not in the table): refuses, logs it, raises.
"""

from . import actions, config
from .actions import ForbiddenAction

AUTO = "auto"
APPROVAL = "approval"
FORBIDDEN = "forbidden"

ALLOWED_ACTIONS = {
    # drafting a reply only saves text in our own database
    "draft_reply": AUTO,
    # changes to Odoo, and sending email, need a named human
    "create_vendor": APPROVAL,
    "create_purchase_order": APPROVAL,
    "update_purchase_order": APPROVAL,
    "send_email": APPROVAL,
    # never, even with approval: a person does these in Odoo themselves
    "confirm_purchase_order": FORBIDDEN,
    "cancel_purchase_order": FORBIDDEN,
    "delete_record": FORBIDDEN,
    # productions (analytic accounts) and budgets belong to finance, never to the agent
    "create_production": FORBIDDEN,
}


class ApprovalRequired(Exception):
    pass


class WritesDisabled(Exception):
    pass


def execute(action: str, *, odoo, store, run_id: str, approved_by: str | None = None, **params):
    rule = ALLOWED_ACTIONS.get(action, FORBIDDEN)  # unknown actions are forbidden
    actor = f"agent, approved by {approved_by}" if approved_by else "agent"

    if rule == FORBIDDEN:
        store.audit(run_id, actor, f"blocked:{action}", after=params)
        raise ForbiddenAction(f"'{action}' is not allowed for this agent")

    if rule == APPROVAL:
        if not approved_by:
            raise ApprovalRequired(f"'{action}' needs a human approval first")
        if not config.writes_enabled():
            store.audit(run_id, actor, f"blocked_by_kill_switch:{action}", after=params)
            raise WritesDisabled("Kill switch is on: no writes allowed")

    handler = getattr(actions, action)
    try:
        return handler(odoo=odoo, store=store, run_id=run_id, actor=actor, **params)
    except ForbiddenAction as e:  # the action found its own rule broken (e.g. outside email)
        store.audit(run_id, actor, f"blocked:{action}", after={**params, "reason": str(e)})
        raise
