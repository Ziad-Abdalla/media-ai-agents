"""Per-production budget check: would this order push the production over its budget?

It only warns. A person still decides, but going over needs an extra tick and a reason
on the approval page (checked again on the server, with fresh numbers, at the click).

"Committed" = every purchase order line charged to the production that isn't cancelled:
drafts, POs waiting for confirmation and confirmed POs. Drafts count on purpose, because
a draft is money someone already plans to spend.

Only SAR and USD (pegged at 3.75) are converted. A PO line in any other currency is left out of
"committed" and named on the page, so nobody reads a wrong total as a right one.
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
    total = 0.0
    for item in request.items:
        currency = (item.currency or "SAR").upper()
        if currency not in TO_SAR:  # validate() only lets SAR and USD through, so this is a setup mistake
            raise ValueError(f"no riyal rate for {currency}; add it to TO_SAR in budget.py")
        total += (item.quantity or 0) * (item.unit_price or 0) * TO_SAR[currency]
    return total


def committed_sar(odoo, analytic_id: int, exclude_origin: str | None = None) -> dict:
    """Riyals already committed to this production: {"sar", "po_count", "not_counted"}.
    exclude_origin leaves out this run's own PO, so a retry doesn't count the order twice.
    not_counted lists currencies of PO lines that were left out because there is no rate for
    them (someone typed a EUR PO in Odoo by hand, say). Odoo only returns this production's
    lines; the share is then read from each line, because one line can be split between two."""
    own = set()
    if exclude_origin:
        own = {p["id"] for p in odoo.search_read("purchase.order", [("origin", "=", exclude_origin)], ["id"])}
    lines = odoo.search_read("purchase.order.line",
                             [("state", "!=", "cancel"), ("analytic_distribution", "in", [analytic_id])],
                             ["order_id", "price_subtotal", "analytic_distribution", "currency_id"])
    total, orders, not_counted = 0.0, set(), set()
    for line in lines:
        share = (line.get("analytic_distribution") or {}).get(str(analytic_id))
        order_id = line["order_id"][0]
        if not share or order_id in own:
            continue
        currency = line["currency_id"][1] if line.get("currency_id") else "SAR"
        if currency not in TO_SAR:
            not_counted.add(currency)
            continue
        total += line["price_subtotal"] * TO_SAR[currency] * share / 100
        orders.add(order_id)
    return {"sar": round(total, 2), "po_count": len(orders), "not_counted": sorted(not_counted)}


def _status(after: float, budget: float) -> tuple[float | None, str]:
    """(% used, ok / near / over). A budget of 0 means "nothing may be spent": any spend is over."""
    if budget <= 0:
        return None, "over" if after > 0 else "ok"
    used = after / budget
    return round(used * 100, 1), "over" if used > 1 else "near" if used >= NEAR else "ok"


def check(odoo, production: dict, amount_sar: float, exclude_origin: str | None = None) -> dict | None:
    """The budget picture for one order. None if the production has no budget on file."""
    plan = budgets().get(production.get("code") or "")
    if not plan:
        return None
    committed = committed_sar(odoo, production["analytic_id"], exclude_origin)
    after = committed["sar"] + amount_sar
    used_pct, status = _status(after, plan["budget"])
    return {
        "production": production["name"], "code": plan["code"], "budget": plan["budget"],
        "committed": committed["sar"], "po_count": committed["po_count"],
        "not_counted": committed["not_counted"], "this_order": round(amount_sar, 2),
        "after": round(after, 2), "used_pct": used_pct, "status": status,
    }


def check_run(odoo, run: dict) -> dict | None:
    """The budget picture for a run's order, leaving out the run's own PO if it already exists.
    None if the production isn't chosen yet or has no budget on file."""
    production = (run.get("resolution_json") or {}).get("production") or {}
    if production.get("status") != "matched" or not run.get("request_json"):
        return None
    request = PurchaseRequest.from_stored(run["request_json"])
    own_po = ORIGIN_PREFIX + run["idempotency_key"] if run.get("idempotency_key") else None
    return check(odoo, production, order_total_sar(request), exclude_origin=own_po)


def production_overview(odoo) -> list[dict]:
    """Every production with a budget: budget, committed and % used. For the KPI report."""
    rows = []
    for account in production_accounts(odoo):
        plan = budgets().get(account.get("code") or "")
        if not plan:
            continue
        committed = committed_sar(odoo, account["id"])
        used_pct, status = _status(committed["sar"], plan["budget"])
        rows.append({"production": account["name"], "code": plan["code"], "budget": plan["budget"],
                     "committed": committed["sar"], "po_count": committed["po_count"],
                     "not_counted": committed["not_counted"], "used_pct": used_pct, "status": status})
    return rows
