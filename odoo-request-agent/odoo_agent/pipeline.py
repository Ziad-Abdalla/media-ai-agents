"""The whole flow for one email, plus what happens when a human clicks a button.

process_email:  email -> extract -> validate -> resolve -> plan -> waits for a human
approve_run:    human said yes -> execute the plan through the permission gate
"""

import re
import uuid
import xmlrpc.client

import anthropic
import pydantic
from agent_cost_tracker import BudgetExceeded

from . import resolve
from .extract import ExtractionFailed, extract_request
from .models import Email, PurchaseRequest
from .permissions import ForbiddenAction, WritesDisabled, execute
from .plan import NEW_VENDOR, build_plan, fingerprint, idempotency_key
from .validate import draft_needs_info_reply, sender_allowed, validate

# Not the defence (the defence is that the model can't act), just a warning for the reviewer.
INJECTION_HINTS = re.compile(
    r"ignore (all |any )?(previous|prior|above|earlier) instructions|you are now|system prompt|"
    r"confirm (the|this) (po|order|purchase order)|forward .* to|send .* (list|data|details) to",
    re.IGNORECASE)


def process_email(email: Email, *, client, odoo, store) -> str | None:
    """Returns the run_id, or None if we've already seen this email."""
    if store.find_run(message_id=email.message_id):
        return None  # same email fetched again: nothing to do, no model call

    run_id = "run-" + uuid.uuid4().hex[:8]
    store.add_run(run_id=run_id, message_id=email.message_id, sender=email.sender,
                  subject=email.subject, body=email.body, received_at=email.received_at,
                  status="received")

    if not sender_allowed(email):
        store.update_run(run_id, status="blocked_sender",
                         error=f"{email.sender} is not an internal sender; ignored")
        return run_id

    # 1. Extract (the only AI step)
    try:
        request = extract_request(client, email, run_id)
    except BudgetExceeded:
        store.update_run(run_id, status="failed", error="cost budget reached")
        raise
    except (ExtractionFailed, pydantic.ValidationError,
            anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APIStatusError) as e:
        store.update_run(run_id, status="failed", error=f"extraction failed: {e}")
        return run_id
    store.update_run(run_id, request_json=request.model_dump())

    # 2. Validate in code
    problems = validate(request, email)
    if problems:
        reply = draft_needs_info_reply(email, problems)
        execute("draft_reply", odoo=odoo, store=store, run_id=run_id, text=reply)
        store.update_run(run_id, status="needs_info", problems_json=problems)
        return run_id

    # 3. Resolve Odoo records (reads only)
    vendor = resolve.resolve_vendor(odoo, request.vendor_name)
    products = resolve.resolve_products(odoo, [i.name for i in request.items])
    currency_id = resolve.resolve_currency(odoo, request.items[0].currency)
    if currency_id is None:
        store.update_run(run_id, status="failed",
                         error=f"currency {request.items[0].currency} is not active in Odoo")
        return run_id
    warnings = []
    if INJECTION_HINTS.search(email.body):
        warnings.append("This email contains text that looks like instructions to the AI. "
                        "It was treated as data. Check the plan against the email.")
    if request.confidence_notes:
        warnings.append("Model notes: " + request.confidence_notes)

    # 4. Keys, duplicate check, plan
    key = idempotency_key(email.message_id, request)
    fp = fingerprint(request)
    earlier = store.find_run(fingerprint=fp)
    plan = build_plan(request, vendor, products, currency_id, key)

    status = "pending_approval"
    if vendor["status"] == "needs_human":
        status = "needs_human"
    if earlier:
        status = "needs_human"
        warnings.append(f"Looks like a re-send of {earlier['run_id']} "
                        f"(status {earlier['status']}). Approve only if a second order is wanted.")

    resolution = {"vendor": vendor, "products": products, "currency_id": currency_id,
                  "warnings": warnings}
    store.update_run(run_id, idempotency_key=key, fingerprint=fp, resolution_json=resolution,
                     plan_json=plan, status=status,
                     duplicate_of=earlier["run_id"] if earlier else None)
    return run_id


def choose_vendor(store, run_id: str, partner_id: int | None, partner_name: str = "") -> None:
    """A human picked the vendor (or chose 'create new'), or confirmed a re-send is wanted.
    Rebuild the plan with that choice and wait for approval."""
    run = store.get_run(run_id)
    request = PurchaseRequest.model_validate(run["request_json"])
    res = run["resolution_json"]
    if partner_id:
        res["vendor"] = {"status": "matched", "partner_id": partner_id, "name": partner_name,
                         "score": None, "candidates": [], "reason": "chosen by a human"}
    elif res["vendor"]["status"] != "matched":
        res["vendor"] = {"status": "new", "partner_id": None, "candidates": [],
                         "reason": "human chose to create a new vendor"}
    plan = build_plan(request, res["vendor"], res["products"], res["currency_id"],
                      run["idempotency_key"])
    store.update_run(run_id, resolution_json=res, plan_json=plan, status="pending_approval")


def approve_run(store, odoo, run_id: str, approver: str) -> int:
    """Run the plan. Safe to call again after a failure: the PO step is idempotent."""
    run = store.get_run(run_id)
    if run["status"] not in ("pending_approval", "write_failed"):
        raise ValueError(f"{run_id} is '{run['status']}', it can't be approved")
    store.update_run(run_id, status="writing", approved_by=approver)
    store.audit(run_id, f"human:{approver}", "approve")

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
    except (OSError, xmlrpc.client.Error) as e:
        # Network trouble or an Odoo error. The PO may or may not exist: retrying is safe.
        store.update_run(run_id, status="write_failed", error=str(e))
        raise
    store.update_run(run_id, status="done", po_id=po_id, error=None)
    return po_id


def reject_run(store, run_id: str, approver: str) -> None:
    store.update_run(run_id, status="rejected", approved_by=approver)
    store.audit(run_id, f"human:{approver}", "reject")
