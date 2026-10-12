"""Prepare the local Odoo: create the database, install Purchase, add demo vendors and products.

Safe to run again: everything is looked up before it's created.
  python scripts/setup_odoo.py

Uses the admin user to keep the demo simple. In a real company the agent gets its own
Odoo user with only Purchase rights, and logs in with an API key instead of a password.
"""

import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from odoo_agent import config  # noqa: E402
from odoo_agent.odoo_client import OdooClient  # noqa: E402

MASTER_PASSWORD = "admin"  # the odoo:17 image default; only for this local demo

VENDORS = ["Riyadh Grip Co", "Riyadh Grip & Lighting", "Desert Lights Rental",
           "Red Sea Sound Studio", "Jeddah Camera House"]
PRODUCTS = ["Camera Crane Rental", "Lighting Kit Rental", "Sound Equipment Rental",
            "Camera Package Rental", "Production Service"]


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


def main():
    create_database()
    odoo = OdooClient()
    install_purchase(odoo)

    # Saudi riyal is in Odoo but switched off by default.
    sar = odoo.call("res.currency", "search_read", [("name", "=", "SAR"), ("active", "in", [True, False])],
                    fields=["id", "active"])
    if sar and not sar[0]["active"]:
        odoo.write("res.currency", sar[0]["id"], {"active": True})
        print("activated SAR")

    for name in VENDORS:
        ensure(odoo, "res.partner", name, {"is_company": True, "supplier_rank": 1})
    for name in PRODUCTS:
        ensure(odoo, "product.product", name, {"type": "service", "purchase_ok": True})
    print("Odoo is ready:", config.ODOO_URL, "database", config.ODOO_DB)


if __name__ == "__main__":
    main()
