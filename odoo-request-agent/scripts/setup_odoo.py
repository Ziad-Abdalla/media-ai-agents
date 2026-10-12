"""Prepare the local Odoo: create the database, install Purchase, add demo vendors, products,
productions (analytic accounts) and some earlier spend per production.

Safe to run again: everything is looked up before it's created.
  python scripts/setup_odoo.py

All of it is SYNTHETIC demo data: fictional vendors, productions and amounts.

Uses the admin user to keep the demo simple. In a real company the agent gets its own
Odoo user with only Purchase rights (plus read access to analytic accounts), and logs in
with an API key instead of a password.
"""

import json
import sys
import xmlrpc.client
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from odoo_agent import config  # noqa: E402
from odoo_agent.odoo_client import OdooClient  # noqa: E402

MASTER_PASSWORD = "admin"  # the odoo:17 image default; only for this local demo

VENDORS = ["Riyadh Grip Co", "Riyadh Grip & Lighting", "Desert Lights Rental",
           "Red Sea Sound Studio", "Jeddah Camera House", "Al-Balad Heritage Homes"]
PRODUCTS = ["Camera Crane Rental", "Lighting Kit Rental", "Sound Equipment Rental",
            "Camera Package Rental", "Production Service",
            # one per cost category, used when an item matches no product above
            "Equipment Rental", "Crew & Freelancer Services", "Location Fee", "Catering Service",
            "Transport Service"]

# Spend that was already committed before the demo starts (confirmed POs), per production code.
# Picked so the demo shows all three budget states: within, close to, and over budget.
EARLIER_SPEND = {
    "RML-S1": [("Riyadh Grip Co", "Camera Crane Rental", 60_000), ("Jeddah Camera House", "Camera Package Rental", 120_000)],
    "BYT-R27": [("Desert Lights Rental", "Lighting Kit Rental", 150_000), ("Red Sea Sound Studio", "Sound Equipment Rental", 120_000)],
    "SHK-S3": [("Riyadh Grip & Lighting", "Lighting Kit Rental", 33_500), ("Red Sea Sound Studio", "Sound Equipment Rental", 20_000)],
}


def create_database():
    db = xmlrpc.client.ServerProxy(f"{config.ODOO_URL}/xmlrpc/2/db")
    if config.ODOO_DB in db.list():
        print(f"database {config.ODOO_DB} already exists")
        return
    print(f"creating database {config.ODOO_DB} (takes a minute)...")
    db.create_database(MASTER_PASSWORD, config.ODOO_DB, False, "en_US", config.ODOO_PASSWORD)


def install_purchase(odoo):
    module = odoo.search_read("ir.module.module", [("name", "=", "purchase")], ["id", "state"])[0]
    if module["state"] == "installed":
        print("purchase already installed")
        return
    print("installing purchase (takes a minute)...")
    odoo.call("ir.module.module", "button_immediate_install", [module["id"]])


def ensure(odoo, model, name, values):
    found = odoo.search_read(model, [("name", "=", name)], ["id"])
    if found:
        return found[0]["id"]
    print(f"creating {model}: {name}")
    return odoo.create(model, {"name": name, **values})


def enable_analytic_accounting(odoo):
    """Analytic accounts are hidden until the user is in the Analytic Accounting group."""
    group = odoo.search_read("ir.model.data", [("module", "=", "analytic"),
                                               ("name", "=", "group_analytic_accounting")], ["res_id"])
    odoo.write("res.users", odoo.uid, {"groups_id": [(4, group[0]["res_id"])]})  # (4, id) = add


def ensure_productions(odoo) -> dict[str, int]:
    """One analytic account per production, under the 'Productions' plan. Returns {code: id}."""
    plan_id = ensure(odoo, "account.analytic.plan", config.PRODUCTION_PLAN, {})
    productions = json.loads(Path(config.BUDGETS_FILE).read_text(encoding="utf-8"))["productions"]
    ids = {}
    for p in productions:
        found = odoo.search_read("account.analytic.account", [("code", "=", p["code"])], ["id"])
        if found:
            ids[p["code"]] = found[0]["id"]
            continue
        print(f"creating production: {p['name']} ({p['code']})")
        ids[p["code"]] = odoo.create("account.analytic.account",
                                     {"name": p["name"], "code": p["code"], "plan_id": plan_id})
    return ids


def ensure_earlier_spend(odoo, production_ids, sar_id):
    """Confirmed POs from 'before the agent', charged to each production, so budgets aren't empty.
    Marked with origin 'demo-seed:...' so they're easy to find (and never touched by rollback)."""
    for code, orders in EARLIER_SPEND.items():
        for n, (vendor, product, amount) in enumerate(orders, start=1):
            origin = f"demo-seed:{code}-{n}"
            if odoo.search_read("purchase.order", [("origin", "=", origin)], ["id"]):
                continue
            partner = odoo.search_read("res.partner", [("name", "=", vendor)], ["id"])[0]["id"]
            product_id = odoo.search_read("product.product", [("name", "=", product)], ["id"])[0]["id"]
            po_id = odoo.create("purchase.order", {
                "partner_id": partner, "currency_id": sar_id, "origin": origin,
                "notes": "Synthetic demo data: earlier spend for the budget check.",
                "order_line": [[0, 0, {"product_id": product_id, "name": f"{product} (earlier order)",
                                       "product_qty": 1, "price_unit": amount,
                                       "analytic_distribution": {str(production_ids[code]): 100}}]],
            })
            odoo.call("purchase.order", "button_confirm", [po_id])
            print(f"seeded earlier spend: {origin} {amount:,} SAR")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    create_database()
    odoo = OdooClient()
    install_purchase(odoo)
    enable_analytic_accounting(odoo)

    # Saudi riyal is in Odoo but switched off by default.
    sar = odoo.search_read("res.currency", [("name", "=", "SAR"), ("active", "in", [True, False])],
                           ["id", "active"])[0]
    if not sar["active"]:
        odoo.write("res.currency", sar["id"], {"active": True})
        print("activated SAR")

    for name in VENDORS:
        ensure(odoo, "res.partner", name, {"is_company": True, "supplier_rank": 1})
    for name in PRODUCTS:
        ensure(odoo, "product.product", name, {"type": "service", "purchase_ok": True})
    production_ids = ensure_productions(odoo)
    ensure_earlier_spend(odoo, production_ids, sar["id"])
    print("Odoo is ready:", config.ODOO_URL, "database", config.ODOO_DB)


if __name__ == "__main__":
    main()
