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
        "items": sorted([i.name.lower().strip(), i.quantity, i.unit_price, (i.currency or "").upper()]
                        for i in request.items),
        "needed_by": request.needed_by,
        "approval": (request.approval_reference or "").upper().strip(),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def idempotency_key(message_id: str, request: PurchaseRequest) -> str:
    """One email + one request = one key = at most one PO."""
    return hashlib.sha256(f"{message_id}|{fingerprint(request)}".encode()).hexdigest()[:20]


def build_plan(request: PurchaseRequest, vendor: dict, products: list[dict],
               currency_id: int, key: str) -> list[dict]:
    steps = []
    if vendor["status"] == "new":
        steps.append({"action": "create_vendor", "model": "res.partner",
                      "values": {"name": request.vendor_name, "is_company": True, "supplier_rank": 1,
                                 "ref": ORIGIN_PREFIX + key}})  # the key, so it can be found again

    date_planned = f"{request.needed_by} 09:00:00"
    lines = []
    for item, product in zip(request.items, products):
        lines.append([0, 0, {  # [0, 0, values] is Odoo's way of saying "create this line"
            "product_id": product["product_id"],
            "name": item.name,
            "product_qty": item.quantity,
            "price_unit": item.unit_price,
            "date_planned": date_planned,
        }])

    steps.append({"action": "create_purchase_order", "model": "purchase.order", "values": {
        "partner_id": vendor["partner_id"] or NEW_VENDOR,
        "partner_ref": request.approval_reference,
        "origin": ORIGIN_PREFIX + key,   # the idempotency key lives in Odoo too
        "currency_id": currency_id,
        "date_planned": date_planned,
        "notes": f"Requested by {request.requester} ({request.department}). Draft created from email.",
        "order_line": lines,
    }})
    return steps
