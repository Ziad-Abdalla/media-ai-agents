"""Test helpers: a fake Odoo (a few Python dicts) and a fake Anthropic client.
Unit tests never touch the network and never spend money."""

import json
from types import SimpleNamespace

import pytest

from odoo_agent import config
from odoo_agent.models import Email
from odoo_agent.pipeline import approve_run
from odoo_agent.plan import plan_hash
from odoo_agent.store import Store

RECEIVED = "2026-10-12T10:00:00+03:00"

NORMAL_REQUEST = {
    "vendor_name": "Riyadh Grip Co",
    "production": "Rimal Al-Khobar",
    "items": [{"name": "Camera crane rental", "quantity": 2, "unit_price": 3500, "currency": "SAR",
               "category": "equipment_rental"}],
    "needed_by": "2026-10-20",
    "requester": "Noura Al-Harbi",
    "department": "Production",
    "approval_reference": "APR-2026-0412",
    "confidence_notes": None,
}


def make_email(body="Please order a crane...", sender="noura@sadaf.example",
               message_id="<msg-1@sadaf.example>", subject="Crane rental"):
    return Email(message_id=message_id, sender=sender, subject=subject, body=body,
                 received_at=RECEIVED)


def approve(store, odoo, run_id, approver="Ziad"):
    """Approve the plan as it is stored right now, like a person who just loaded the page."""
    shown = plan_hash(store.get_run(run_id)["plan_json"])
    return approve_run(store, odoo, run_id, approver, shown)


# The same fictional productions as production_budgets.json (the budgets come from that file).
PRODUCTIONS = {"RML-S1": "Rimal Al-Khobar (رمال الخبر)", "BYT-R27": "Bayt Al-Jadd (بيت الجد)",
               "SHK-S3": "Sahrat Al-Khamis (سهرة الخميس)"}


class FakeOdoo:
    """Just enough of OdooClient for the tests: search_read, create, write, call.
    purchase.order.line is not stored separately: it is read out of each PO's order_line."""

    def __init__(self):
        self.records = {"res.partner": {}, "product.product": {}, "res.currency": {},
                        "purchase.order": {}, "account.analytic.plan": {},
                        "account.analytic.account": {}}
        self.next_id = 1
        self.lose_next_create_answer = False  # simulate: Odoo saved it, but our reply got lost
        for name in ["Riyadh Grip Co", "Riyadh Grip & Lighting", "Desert Lights Rental",
                     "Red Sea Sound Studio"]:
            self._add("res.partner", {"name": name, "ref": False, "supplier_rank": 1, "active": True})
        for name in ["Camera Crane Rental", "Lighting Kit Rental", "Production Service"]:
            self._add("product.product", {"name": name, "purchase_ok": True})
        self.sar = self._add("res.currency", {"name": "SAR"})
        for name in ["Location Fee", "Crew & Freelancer Services"]:
            self._add("product.product", {"name": name, "purchase_ok": True})
        plan = self._add("account.analytic.plan", {"name": "Productions"})
        self.production_ids = {
            code: self._add("account.analytic.account", {"name": name, "code": code, "plan_id": plan})
            for code, name in PRODUCTIONS.items()}

    def commit_spend(self, code, amount):
        """An existing confirmed PO of `amount` SAR charged to production `code`."""
        line = {"product_id": 1, "name": "earlier order", "product_qty": 1, "price_unit": amount,
                "analytic_distribution": {str(self.production_ids[code]): 100}}
        po_id = self.create("purchase.order", {"partner_id": 1, "currency_id": self.sar,
                                               "origin": f"earlier-{self.next_id}",
                                               "order_line": [[0, 0, line]]})
        self.records["purchase.order"][po_id]["state"] = "purchase"
        return po_id

    def _lines(self):
        for po in self.records["purchase.order"].values():
            for _, _, line in po.get("order_line", []):
                currency = self.records["res.currency"].get(po.get("currency_id"), {}).get("name", "SAR")
                yield {"state": po["state"], "order_id": [po["id"], po["name"]],
                       "price_subtotal": line["product_qty"] * line["price_unit"],
                       "analytic_distribution": line.get("analytic_distribution", False),
                       "currency_id": [po.get("currency_id"), currency]}

    def _add(self, model, values):
        rid = self.next_id
        self.next_id += 1
        self.records[model][rid] = {"id": rid, **values}
        return rid

    def _matches(self, record, domain):
        for field, op, value in domain:
            have = record.get(field)
            if op == "=" and have != value:
                return False
            if op == "!=" and have == value:
                return False
            if op == ">" and not (have or 0) > value:
                return False
            if op == "in" and have not in value:
                return False
        return True

    def search_read(self, model, domain, fields):
        if model == "purchase.order.line":
            return [line for line in self._lines() if self._matches(line, domain)]
        return [{f: r.get(f) for f in ["id", *fields]}
                for r in self.records[model].values()
                if r.get("active", True) and self._matches(r, domain)]

    def create(self, model, values):
        if model == "purchase.order":
            values = {"state": "draft", "name": f"P{self.next_id:05d}", **values}
        rid = self._add(model, values)
        if self.lose_next_create_answer:
            self.lose_next_create_answer = False
            raise ConnectionResetError("connection dropped before Odoo answered")
        return rid

    def write(self, model, record_id, values):
        self.records[model][record_id].update(values)
        return True

    def call(self, model, method, ids):
        for rid in ids:
            if method == "button_cancel":
                self.records[model][rid]["state"] = "cancel"
            elif method == "unlink":
                del self.records[model][rid]
            else:
                raise NotImplementedError(method)
        return True

    def pos(self):
        return list(self.records["purchase.order"].values())


class FakeAnthropic:
    """Returns a canned extraction. Remembers every request so tests can inspect it."""

    def __init__(self, request=NORMAL_REQUEST, stop_reason="end_turn"):
        self.reply = json.dumps(request)
        self.stop_reason = stop_reason
        self.sent = []
        self.messages = self

    def create(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"], stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=900, output_tokens=150,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0),
            content=[SimpleNamespace(type="thinking", thinking="..."),
                     SimpleNamespace(type="text", text=self.reply)])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own cost ledger, kill switch file and settings."""
    monkeypatch.setenv("COST_DB_PATH", str(tmp_path / "costs.sqlite"))
    monkeypatch.setenv("COST_BUDGET_USD", "15")
    monkeypatch.setenv("AGENT_WRITES_ENABLED", "true")
    monkeypatch.setattr(config, "KILL_SWITCH_FILE", str(tmp_path / "agent.kill"))
    monkeypatch.setattr(config, "COMPANY_DOMAINS", ["sadaf.example"])
    monkeypatch.setattr(config, "ALLOWED_CURRENCIES", ["SAR", "USD"])


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "agent.sqlite"))


@pytest.fixture
def odoo():
    return FakeOdoo()
