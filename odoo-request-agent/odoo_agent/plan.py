"""Turning a checked request into an exact write plan, plus the idempotency key.

A plan is a list of steps like:
  {"action": "create_purchase_order", "model": "purchase.order", "values": {...}}
It's shown on the approval page exactly as it will be sent to Odoo.
"""

import hashlib
import json

from .actions import ORIGIN_PREFIX
from .models import PurchaseRequest

NEW_VENDOR = "<id of the new vendor>"  # filled in after the create_vendor step runs


def fingerprint(request: PurchaseRequest) -> str:
    """Hash of the parts of the request that matter. Same order, same fingerprint,
    even if the wording or the model's notes differ."""
    core = {
        "vendor": " ".join((request.vendor_name or "").lower().split()),
        "production": " ".join((request.production or "").lower().split()),
        "items": sorted([i.name.lower().strip(), i.quantity, i.unit_price, (i.currency or "").upper()]
                        for i in request.items),
        "needed_by": request.needed_by,
        "approval": (request.approval_reference or "").upper().strip(),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def plan_hash(plan) -> str:
    """Hash of the exact plan. The approval page shows it and sends it back with the click,
    so Approve only runs the plan the person actually saw. Any change to the plan changes it."""
    canonical = json.dumps(plan, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def idempotency_key(message_id: str, request: PurchaseRequest) -> str:
    """One email + one request = one key = at most one PO."""
    return hashlib.sha256(f"{message_id}|{fingerprint(request)}".encode()).hexdigest()[:20]


def build_plan(request: PurchaseRequest, vendor: dict, products: list[dict],
               currency_id: int, key: str, production: dict | None = None) -> list[dict]:
    """production is the matched analytic account. Until a person picks one, the lines carry no
    analytic_distribution, and the run can't be approved (it is waiting in needs_human)."""
    steps = []
    analytic_id = (production or {}).get("analytic_id")
    if vendor["status"] == "new":
        steps.append({"action": "create_vendor", "model": "res.partner",
                      "values": {"name": request.vendor_name, "is_company": True, "supplier_rank": 1,
                                 "ref": ORIGIN_PREFIX + key}})  # the key, so it can be found again

    date_planned = f"{request.needed_by} 09:00:00"
    lines = []
    for item, product in zip(request.items, products):
        line = {
            "product_id": product["product_id"],
            "name": item.name,
            "product_qty": item.quantity,
            "price_unit": item.unit_price,
            "date_planned": date_planned,
        }
        if analytic_id:
            # Charge 100% of the line to the production. Odoo 17 keeps this as JSON
            # {"<analytic account id>": percent}, so the key is a string.
            line["analytic_distribution"] = {str(analytic_id): 100}
        lines.append([0, 0, line])  # [0, 0, values] is Odoo's way of saying "create this line"

    steps.append({"action": "create_purchase_order", "model": "purchase.order", "values": {
        "partner_id": vendor["partner_id"] or NEW_VENDOR,
        "partner_ref": request.approval_reference,
        "origin": ORIGIN_PREFIX + key,   # the idempotency key lives in Odoo too
        "currency_id": currency_id,
        "date_planned": date_planned,
        "notes": (f"Production: {production['name'] if analytic_id else request.production}. "
                  f"Requested by {request.requester} ({request.department}). Draft created from email."),
        "order_line": lines,
    }})
    return steps
