"""Optional: also put approved bookings into Odoo, as a To-Do activity with the shoot date as deadline.

Off by default. The workflow checks app_settings.odoo_sync after every approval, so turning it
on or off takes effect on the next booking, with no restart.

    python scripts/odoo_link.py on          # link the catalogue to Odoo records, then switch it on
    python scripts/odoo_link.py off         # switch it off (bookings still work, Odoo is skipped)
    python scripts/odoo_link.py status      # the switch, the links, and each booking's Odoo state
    python scripts/odoo_link.py undo 3      # roll back: remove booking 3's activity from Odoo

Where the activity goes: equipment that already exists as a product in Odoo gets the activity
on that product (so opening "Camera Crane Rental" shows its upcoming bookings). Everything else
(studios, crew, locations) goes on the company's own contact record. The script never creates
products or contacts in Odoo; it only reads them, and later the workflow adds activities.

Uses the local Odoo from the odoo-request-agent project (database sadaf_demo). Standard library only.
"""
import pathlib
import subprocess
import sys
import xmlrpc.client

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Catalogue code -> name of an existing Odoo product. Codes not listed use the company contact.
PRODUCT_FOR = {
    "CAM-ALEXA-LF": "Camera Package Rental",
    "LENS-SIG-PRIME": "Camera Package Rental",
    "CRANE-JIB-30": "Camera Crane Rental",
    "LIGHT-SKYPANEL": "Lighting Kit Rental",
}


def env():
    values = {"ODOO_URL": "http://host.docker.internal:8069", "ODOO_DB": "sadaf_demo",
              "ODOO_USER": "admin", "ODOO_PASSWORD": "admin"}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in values:
                    values[k.strip()] = v.strip()
    # n8n (in Docker) reaches Odoo as host.docker.internal; this script runs on your machine.
    values["ODOO_URL"] = values["ODOO_URL"].replace("host.docker.internal", "localhost")
    return values


def psql(sql):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "bookings", "-d", "bookings_app",
         "-v", "ON_ERROR_STOP=1", "-At", "-F", "|", "-c", sql],
        cwd=ROOT, capture_output=True, text=True, encoding="utf8")
    if out.returncode != 0:
        sys.exit(out.stderr)
    return [line.split("|") for line in out.stdout.splitlines() if line]


class Odoo:
    def __init__(self, e):
        self.db, self.password = e["ODOO_DB"], e["ODOO_PASSWORD"]
        common = xmlrpc.client.ServerProxy(f"{e['ODOO_URL']}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, e["ODOO_USER"], self.password, {})
        if not self.uid:
            sys.exit("could not log in to Odoo (check ODOO_* in .env)")
        self.models = xmlrpc.client.ServerProxy(f"{e['ODOO_URL']}/xmlrpc/2/object")

    def call(self, model, method, *args, **kw):
        return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kw)

    def one_id(self, model, domain):
        ids = self.call(model, "search", domain, limit=1)
        return ids[0] if ids else None


def link_on():
    odoo = Odoo(env())
    model_id = {m: odoo.one_id("ir.model", [["model", "=", m]]) for m in ("product.template", "res.partner")}
    company_partner = odoo.call("res.users", "read", [odoo.uid], fields=["company_id"])[0]["company_id"][0]
    company_partner = odoo.call("res.company", "read", [company_partner], fields=["partner_id"])[0]["partner_id"][0]
    todo = odoo.one_id("mail.activity.type", [["name", "=", "To-Do"]])
    if not todo:
        sys.exit("no 'To-Do' activity type in Odoo")

    for (code,) in psql("SELECT code FROM resources ORDER BY code"):
        product = PRODUCT_FOR.get(code)
        pid = odoo.one_id("product.template", [["name", "=", product]]) if product else None
        if pid:
            target = (model_id["product.template"], pid, f"product '{product}'")
        else:
            target = (model_id["res.partner"], company_partner, "company contact")
        psql(f"UPDATE resources SET odoo_res_model_id = {int(target[0])}, odoo_res_id = {int(target[1])} "
             f"WHERE code = '{code}'")
        print(f"{code:18} -> {target[2]}")

    psql(f"INSERT INTO app_settings VALUES ('odoo_activity_type_id', '{int(todo)}'), ('odoo_user_id', '{int(odoo.uid)}') "
         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value")
    psql("UPDATE app_settings SET value = 'on' WHERE key = 'odoo_sync'")
    print("odoo_sync is ON: the next approved booking also becomes a To-Do activity in Odoo")


def link_off():
    psql("UPDATE app_settings SET value = 'off' WHERE key = 'odoo_sync'")
    print("odoo_sync is OFF: approved bookings are saved and confirmed, Odoo is skipped")


def status():
    print("odoo_sync =", psql("SELECT value FROM app_settings WHERE key = 'odoo_sync'")[0][0])
    for row in psql("SELECT id, item, odoo_sync, coalesce(odoo_activity_id::text, ''), "
                    "coalesce(replace(odoo_error, chr(10), ' '), '') FROM bookings ORDER BY id"):
        print("booking " + " | ".join(row))


def undo(booking_id):
    rows = psql(f"SELECT odoo_activity_id FROM bookings WHERE id = {int(booking_id)} AND odoo_sync = 'synced'")
    if not rows:
        sys.exit(f"booking {booking_id} has nothing in Odoo to undo")
    activity = int(rows[0][0])
    odoo = Odoo(env())
    if odoo.call("mail.activity", "search", [["id", "=", activity]]):
        odoo.call("mail.activity", "unlink", [activity])
    psql(f"UPDATE bookings SET odoo_sync = 'rolled_back' WHERE id = {int(booking_id)}")
    print(f"booking {booking_id}: activity {activity} removed from Odoo; the booking itself is kept")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["on"]:
        link_on()
    elif args == ["off"]:
        link_off()
    elif args == ["status"]:
        status()
    elif len(args) == 2 and args[0] == "undo" and args[1].isdigit():
        undo(args[1])
    else:
        sys.exit(__doc__)
