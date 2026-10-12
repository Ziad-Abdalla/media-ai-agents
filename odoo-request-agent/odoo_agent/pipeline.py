"""The whole flow for one email, plus what happens when a human clicks a button.

process_email:  email -> extract -> validate -> resolve -> plan -> waits for a human
approve_run:    human said yes to the plan they saw -> budget check -> execute it through the
                permission gate
resolve_needs_human / reject_run: the other buttons on the approval page

Every run also records first_status (where the agent left it before any person touched it) and
planned_at, so the KPI report can tell auto-resolved runs from ones that needed a human.
"""

import re
import uuid
import xmlrpc.client

import anthropic
import pydantic
from agent_cost_tracker import BudgetExceeded

from . import budget, config, resolve
from .extract import ExtractionFailed, extract_request
from .models import Email, PurchaseRequest
from .permissions import ForbiddenAction, WritesDisabled, execute
from .plan import NEW_VENDOR, build_plan, fingerprint, idempotency_key, plan_hash
from .store import now
from .validate import draft_needs_info_reply, sender_allowed, validate

# Not the defence (the defence is that the model can't act), just a warning for the reviewer.
INJECTION_HINTS = re.compile(
    r"ignore (all |any )?(previous|prior|above|earlier) instructions|you are now|system prompt|"
    r"confirm (the|this) (po|order|purchase order)|forward .* to|send .* (list|data|details) to",
    re.IGNORECASE)


def process_email(email: Email, *, client, odoo, store) -> str | None:
    """Returns the run_id, or None if there is nothing to do."""
    if email.sender == config.AGENT_EMAIL.lower():
        return None  # our own reply landed in the same inbox: never treat it as a request

    earlier = store.find_run(message_id=email.message_id)
    if earlier and earlier["status"] != "failed":
        return None  # same email fetched again: nothing to do, no model call

    if earlier:  # the last try failed (rate limit, network...): try again on the same run
        run_id = earlier["run_id"]
        store.update_run(run_id, status="received", error=None)
    else:
        run_id = "run-" + uuid.uuid4().hex[:8]
        store.add_run(run_id=run_id, message_id=email.message_id, sender=email.sender,
                      subject=email.subject, body=email.body, received_at=email.received_at,
                      status="received")

    if not sender_allowed(email):
        store.update_run(run_id, status="blocked_sender", first_status="blocked_sender",
                         error=f"{email.sender} is not an internal sender; ignored")
        return run_id

    # Odoo down, or the agent's user can't read analytic accounts: mark the run failed, so the
    # next poll tries it again. (Left as "received", it would be skipped forever.)
    try:
        productions = [a["name"] for a in resolve.production_accounts(odoo)]
    except (xmlrpc.client.Error, OSError) as e:
        store.update_run(run_id, status="failed", error=f"could not read Odoo: {e}")
        return run_id

    # 1. Extract (the only AI step)
    try:
        request = extract_request(client, email, run_id, productions=productions)
    except BudgetExceeded:
        store.update_run(run_id, status="failed", error="cost budget reached")
        raise
    except (ExtractionFailed, pydantic.ValidationError,
            anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APIStatusError) as e:
        store.update_run(run_id, status="failed", first_status="failed",
                         error=f"extraction failed: {e}")
        return run_id
    store.update_run(run_id, request_json=request.model_dump())

    # 2. Validate in code
    problems = validate(request, email)
    if problems:
        reply = draft_needs_info_reply(email, problems)
        execute("draft_reply", odoo=odoo, store=store, run_id=run_id, text=reply)
        store.update_run(run_id, status="needs_info", first_status="needs_info",
                         problems_json=problems, planned_at=now())
        return run_id

    # 3. Resolve Odoo records (reads only)
    try:
        vendor = resolve.resolve_vendor(odoo, request.vendor_name)
        production = resolve.resolve_production(odoo, request.production)
        products = resolve.resolve_products(odoo, [i.name for i in request.items],
                                            [i.category for i in request.items])
        currency_id = resolve.resolve_currency(odoo, request.items[0].currency)
    except (xmlrpc.client.Error, OSError) as e:
        store.update_run(run_id, status="failed", error=f"could not read Odoo: {e}")
        return run_id
    if currency_id is None:
        store.update_run(run_id, status="failed", first_status="failed",
                         error=f"currency {request.items[0].currency} is not active in Odoo")
        return run_id
    # Warnings (red on the page) are for things a person must look at. The model's ordinary
    # notes ("currency guessed from the price") are shown in a plain box, so red keeps its meaning.
    warnings = []
    if INJECTION_HINTS.search(email.body) or request.suspicious_instructions:
        warnings.append("This email contains text that looks like instructions to the AI. "
                        "It was treated as data. Check the plan against the email.")
    notes = request.confidence_notes or ""

    # 4. Keys, duplicate check, plan
    key = idempotency_key(email.message_id, request)
    fp = fingerprint(request)
    earlier = store.find_run(fingerprint=fp)
    plan = build_plan(request, vendor, products, currency_id, key, production)

    status = "pending_approval"
    if vendor["status"] == "needs_human" or production["status"] == "needs_human":
        status = "needs_human"
    if earlier:
        status = "needs_human"
        warnings.append(f"Looks like a re-send of {earlier['run_id']} "
                        f"(status {earlier['status']}). Approve only if a second order is wanted.")

    resolution = {"vendor": vendor, "production": production, "products": products,
                  "currency_id": currency_id, "warnings": warnings, "notes": notes}
    store.update_run(run_id, idempotency_key=key, fingerprint=fp, resolution_json=resolution,
                     plan_json=plan, status=status, first_status=status, planned_at=now(),
                     duplicate_of=earlier["run_id"] if earlier else None)
    return run_id


def resolve_needs_human(store, run_id: str, partner_id: int | None = None, partner_name: str = "",
                        *, new_vendor: bool = False, production_id: int | None = None,
                        confirm_resend: bool = False, chosen_by: str = "human") -> None:
    """A person answered a 'needs_human' question. For the vendor:
      - picked one of the candidate vendors        -> partner_id is set
      - chose 'none of these, create a new vendor' -> new_vendor=True
    For the production: production_id, which must be one of the productions offered.
    For a likely re-send: confirm_resend=True says "yes, this really is a second order".
    Every open question must be answered. Then the plan is rebuilt and waits for approval."""
    run = store.get_run(run_id)
    if not run or run["status"] != "needs_human":
        # Only open questions can be answered. A rejected or rolled-back run stays closed.
        raise ValueError(f"{run_id} is not waiting for a human choice")
    request = PurchaseRequest.model_validate(run["request_json"])
    res = run["resolution_json"]
    production = res.get("production") or {}

    if partner_id:
        res["vendor"] = {"status": "matched", "partner_id": partner_id, "name": partner_name,
                         "score": None, "candidates": [], "reason": "chosen by a human"}
    elif new_vendor and res["vendor"]["status"] != "matched":
        res["vendor"] = {"status": "new", "partner_id": None, "candidates": [],
                         "reason": "human chose to create a new vendor"}
    elif res["vendor"]["status"] == "needs_human":
        raise ValueError("choose a vendor first")

    if run["duplicate_of"] and not confirm_resend:
        raise ValueError(f"confirm that this is a new order, not a re-send of {run['duplicate_of']}")

    if production.get("status") == "needs_human":
        offered = {c["id"]: c for c in production.get("candidates", [])}
        if production_id not in offered:
            raise ValueError("choose the production from the list first")
        pick = offered[production_id]
        res["production"] = {"status": "matched", "analytic_id": pick["id"], "name": pick["name"],
                             "code": pick.get("code"), "score": None, "candidates": [],
                             "reason": "chosen by a human"}

    plan = build_plan(request, res["vendor"], res["products"], res["currency_id"],
                      run["idempotency_key"], res.get("production"))
    store.update_run(run_id, resolution_json=res, plan_json=plan, status="pending_approval")
    store.audit(run_id, f"human:{chosen_by}", "human_choice",
                after={"vendor": res["vendor"].get("name") or res["vendor"]["status"],
                       "production": (res.get("production") or {}).get("name"),
                       "confirmed_resend": bool(run["duplicate_of"]),
                       "duplicate_of": run["duplicate_of"]})


def approve_run(store, odoo, run_id: str, approver: str, shown_plan_hash: str,
                over_budget_reason: str = "") -> int:
    """Run the plan. Safe to call again after a failure: the PO step is idempotent.
    shown_plan_hash is the hash of the plan the approver saw on the page. If the plan has
    changed since then (someone answered a question and it was rebuilt), nothing is written.
    If the order takes its production over budget, the approver must also write a reason."""
    approver = approver.strip()
    if not approver:
        raise ValueError("type your name to approve")

    # Budget, with fresh numbers from Odoo: other POs may have been approved since the page
    # loaded. On the page it is a warning; here, "over budget" needs a written reason.
    run = store.get_run(run_id)
    waiting = run and run["status"] in ("pending_approval", "write_failed")
    money = budget.check_run(odoo, run) if waiting else None
    over = money is not None and money["status"] == "over"
    if over and not over_budget_reason.strip():
        store.audit(run_id, f"human:{approver}", "refused: over budget without a reason", after=money)
        raise ValueError(f"this order takes {money['production']} to {money['used_pct']}% of its "
                         "budget; tick the over-budget box and write a reason to approve anyway")
    # One database step checks the status AND the plan hash, and sets the status to 'writing'.
    # Two clicks at the same moment can't both get past this line, so they can't both create
    # a PO. And a click on an old copy of the page can't approve a plan nobody looked at.
    if not store.claim_for_writing(run_id, approver, shown_plan_hash or ""):
        run = store.get_run(run_id)
        if not run or run["status"] not in ("pending_approval", "write_failed"):
            status = run["status"] if run else "unknown"
            raise ValueError(f"{run_id} is '{status}', it can't be approved")
        store.audit(run_id, f"human:{approver}", "refused: plan changed since you viewed it",
                    before={"shown_plan_hash": shown_plan_hash},
                    after={"current_plan_hash": plan_hash(run["plan_json"])})
        raise ValueError("the plan changed after you opened the page; reload and review again")
    store.audit(run_id, f"human:{approver}", "approve")
    if over:
        store.audit(run_id, f"human:{approver}", "approve_over_budget",
                    after={**money, "reason": over_budget_reason.strip()})
    run = store.get_run(run_id)  # read AFTER the claim: this is the plan that was approved

    partner_id = po_id = None
    try:
        for step in run["plan_json"]:
            values = dict(step["values"])
            if values.get("partner_id") == NEW_VENDOR:
                values["partner_id"] = partner_id
            result = execute(step["action"], odoo=odoo, store=store, run_id=run_id,
                             approved_by=approver, values=values)
            if step["action"] == "create_vendor":
                partner_id = result
            else:
                po_id = result
    except (WritesDisabled, ForbiddenAction) as e:
        store.update_run(run_id, status="pending_approval", error=str(e))
        raise
    except Exception as e:
        # Network trouble, an Odoo error, or a bug. The PO may or may not exist: retrying is
        # safe because the create steps search Odoo first. Never leave the run stuck in 'writing'.
        store.update_run(run_id, status="write_failed", error=str(e))
        raise
    store.update_run(run_id, status="done", po_id=po_id, error=None)
    return po_id


def reject_run(store, run_id: str, approver: str) -> None:
    approver = approver.strip()
    run = store.get_run(run_id)
    if not approver or not run or run["status"] not in ("pending_approval", "needs_human", "needs_info"):
        raise ValueError(f"{run_id} can't be rejected now (or no name was typed)")
    store.update_run(run_id, status="rejected", approved_by=approver)
    store.audit(run_id, f"human:{approver}", "reject")
