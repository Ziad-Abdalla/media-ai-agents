"""Per-production budget check: would this order push the production over its budget?

It only warns. A person still decides, but going over needs an extra tick and a reason
on the approval page (checked again on the server, with fresh numbers, at the click).

"Committed" = every purchase order line charged to the production that isn't cancelled:
drafts, POs waiting for confirmation and confirmed POs. Drafts count on purpose, because
a draft is money someone already plans to spend.
"""

import json
from functools import lru_cache

from . import config
from .actions import ORIGIN_PREFIX
from .models import PurchaseRequest
from .resolve import production_accounts

NEAR = 0.90  # at 90% of the budget or more, the page shows "close to budget"
TO_SAR = {"SAR": 1.0, "USD": 3.75}  # the riyal is pegged to the dollar at 3.75


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def budgets() -> dict[str, dict]:
    """{code: {"code", "name", "kind", "budget"}} from production_budgets.json."""
    return {p["code"]: p for p in _load(config.BUDGETS_FILE)["productions"]}


def order_total_sar(request) -> float:
    """What this request would add, before VAT, in riyals."""
    return sum((i.quantity or 0) * (i.unit_price or 0) * TO_SAR.get((i.currency or "SAR").upper(), 1.0)
               for i in request.items)


def committed_sar(odoo, analytic_id: int, exclude_origin: str | None = None) -> tuple[float, int]:
    """Riyals already committed to this production, and on how many POs.
    exclude_origin leaves out this run's own PO, so a retry doesn't count the order twice.
    (Reads every open PO line and adds up in Python; fine for a demo. At scale use read_group.)"""
    own = set()
    if exclude_origin:
        own = {p["id"] for p in odoo.search_read("purchase.order", [("origin", "=", exclude_origin)], ["id"])}
    lines = odoo.search_read("purchase.order.line", [("state", "!=", "cancel")],
                             ["order_id", "price_subtotal", "analytic_distribution", "currency_id"])
    total, orders = 0.0, set()
    for line in lines:
        share = (line.get("analytic_distribution") or {}).get(str(analytic_id))
        order_id = line["order_id"][0]
        if not share or order_id in own:
            continue
        currency = line["currency_id"][1] if line.get("currency_id") else "SAR"
        total += line["price_subtotal"] * TO_SAR.get(currency, 1.0) * share / 100
        orders.add(order_id)
    return round(total, 2), len(orders)


def check(odoo, production: dict, amount_sar: float, exclude_origin: str | None = None) -> dict | None:
    """The budget picture for one order. None if the production has no budget on file."""
    plan = budgets().get(production.get("code") or "")
    if not plan:
        return None
    committed, po_count = committed_sar(odoo, production["analytic_id"], exclude_origin)
    after = committed + amount_sar
    used = after / plan["budget"]
    return {
        "production": production["name"], "code": plan["code"], "budget": plan["budget"],
        "committed": committed, "po_count": po_count, "this_order": round(amount_sar, 2),
        "after": round(after, 2), "used_pct": round(used * 100, 1),
        "status": "over" if used > 1 else "near" if used >= NEAR else "ok",
    }


def check_run(odoo, run: dict) -> dict | None:
    """The budget picture for a run's order, leaving out the run's own PO if it already exists.
    None if the production isn't chosen yet or has no budget on file."""
    production = (run.get("resolution_json") or {}).get("production") or {}
    if production.get("status") != "matched" or not run.get("request_json"):
        return None
    request = PurchaseRequest.model_validate(run["request_json"])
    own_po = ORIGIN_PREFIX + run["idempotency_key"] if run.get("idempotency_key") else None
    return check(odoo, production, order_total_sar(request), exclude_origin=own_po)


def production_overview(odoo) -> list[dict]:
    """Every production with a budget: budget, committed and % used. For the KPI report."""
    rows = []
    for account in production_accounts(odoo):
        plan = budgets().get(account.get("code") or "")
        if not plan:
            continue
        committed, po_count = committed_sar(odoo, account["id"])
        rows.append({"production": account["name"], "code": plan["code"], "budget": plan["budget"],
                     "committed": committed, "po_count": po_count,
                     "used_pct": round(committed / plan["budget"] * 100, 1)})
    return rows
