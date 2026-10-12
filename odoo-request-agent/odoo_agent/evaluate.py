"""Measure extraction accuracy on labelled emails, before changing the prompt, model or effort.

  python -m odoo_agent eval                    current settings (effort low), saves evals/last_run.json
  python -m odoo_agent eval --effort medium    same emails at another effort, saved as its own file
  python -m odoo_agent eval --repeats 3        read every email 3 times: is the model consistent?

The emails and their right answers are in samples/requests.json (synthetic, written by hand).
Each email is read by the model exactly like in production, then every field is compared with
the right answer. It costs about $0.0003 per email, and the calls are filed in the cost ledger
under their own operation name, so they never mix with real requests.

What "right" means per field:
  vendor        same name after cleaning (case, punctuation, "Co", "Est" ...)
  production    a code: must resolve to that production
                "unsure": the email names it too vaguely ("the رمال shoot"); the model must copy
                what it says (not null) and the agent must NOT be sure, so a person picks it
                null: the email doesn't name one; the model must return null (the sender is asked)
  approval / needed_by / currency    exactly equal (null when the email doesn't say)
  quantities / unit prices / categories    equal, item by item
  injection_flag  suspicious_instructions is true on emails with an injection AND false on
                  clean ones. (Scoring "wrote any note" would pass on almost every email.)
"""

import json
import time
from datetime import date
from pathlib import Path

from agent_cost_tracker import ledger

from . import config
from .budget import budgets
from .extract import ExtractionFailed, extract_request
from .models import Email
from .resolve import match_production, normalize

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_FILE = ROOT / "samples" / "requests.json"
EVAL_DIR = ROOT / "evals"
OPERATION = "eval_extract_purchase_request"


def _accounts() -> list[dict]:
    """The productions as the resolver sees them, without needing Odoo."""
    return [{"id": n, "name": p["name"], "code": code} for n, (code, p) in enumerate(budgets().items(), 1)]


def check_fields(got, expected: dict, accounts: list[dict]) -> dict[str, bool]:
    """Compare one extraction with its label. Returns {field: right?}."""
    production = match_production(got.production, accounts)
    resolved = production.get("code") if production["status"] == "matched" else None
    if expected["production"] == "unsure":
        production_right = bool(got.production) and resolved is None
    else:
        production_right = (got.production is None if expected["production"] is None
                            else resolved == expected["production"])
    currencies = {(i.currency or "").upper() or None for i in got.items}
    items = expected["items"]
    result = {
        "vendor": normalize(got.vendor_name or "") == normalize(expected["vendor_name"] or ""),
        "production": production_right,
        "approval_reference": (got.approval_reference or None) == expected["approval_reference"],
        "needed_by": got.needed_by == expected["needed_by"],
        "currency": currencies == {expected["currency"]},
        "quantities": [i.quantity for i in got.items] == [i["quantity"] for i in items],
        "unit_prices": [i.unit_price for i in got.items] == [i["unit_price"] for i in items],
        "categories": [i.category for i in got.items] == [i["category"] for i in items],
        "injection_flag": got.suspicious_instructions == expected["flags_injection"],
    }
    return result


def run_eval(client, effort: str = "low", repeats: int = 1) -> dict:
    data = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
    cases = [s for s in data["samples"] if s.get("eval", True) and "expected" in s]
    accounts = _accounts()
    started = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    per_email, misses = [], []

    for case, repeat in [(c, r) for r in range(repeats) for c in cases]:
        email = Email(message_id=f"<eval-{case['id']}>", sender=case["sender"], subject=case["subject"],
                      body=case["body"], received_at=data["eval_received_at"])
        try:
            got = extract_request(client, email, f"eval-{case['id']}-{repeat}", effort=effort, operation=OPERATION,
                                  productions=[a["name"] for a in accounts])
        except ExtractionFailed as e:
            per_email.append({"id": case["id"], "repeat": repeat, "error": str(e), "fields": {}})
            misses.append({"id": case["id"], "field": "everything", "got": str(e)})
            continue
        fields = check_fields(got, case["expected"], accounts)
        per_email.append({"id": case["id"], "repeat": repeat, "fields": fields})
        for field, ok in fields.items():
            if not ok:
                misses.append({"id": case["id"], "repeat": repeat, "field": field,
                               "got": got.model_dump(include={"vendor_name", "production", "approval_reference",
                                                              "needed_by", "items", "confidence_notes",
                                                              "suspicious_instructions"})})

    conn = ledger.connect()
    cost, latency = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0), AVG(latency_ms) FROM calls WHERE operation = ? AND ts >= ?",
        (OPERATION, started)).fetchone()
    conn.close()

    checked = [ok for e in per_email for ok in e["fields"].values()]
    field_names = sorted({f for e in per_email for f in e["fields"]})
    summary = {
        "date": date.today().isoformat(), "model": config.MODEL, "effort": effort,
        "emails": len(cases), "repeats": repeats, "readings": len(per_email),
        "fields_checked": len(checked),
        "field_accuracy_pct": round(sum(checked) / len(checked) * 100, 1) if checked else 0.0,
        "readings_all_correct": sum(1 for e in per_email if e["fields"] and all(e["fields"].values())),
        "per_field_pct": {f: round(sum(e["fields"][f] for e in per_email if f in e["fields"]) /
                                   sum(1 for e in per_email if f in e["fields"]) * 100, 1)
                          for f in field_names},
        "cost_usd": round(cost, 5), "mean_latency_ms": round(latency or 0),
    }
    return {"summary": summary, "misses": misses, "per_email": per_email,
            "_note": "Synthetic labelled emails from samples/requests.json; not Sadaf data."}


def save(result: dict) -> Path:
    EVAL_DIR.mkdir(exist_ok=True)
    effort = result["summary"]["effort"]
    path = EVAL_DIR / ("last_run.json" if effort == "low" else f"last_run_effort_{effort}.json")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def as_text(result: dict) -> str:
    s = result["summary"]
    lines = [f"Extraction eval: {s['model']}, effort {s['effort']}, {s['emails']} labelled synthetic emails"
             f" x {s['repeats']}",
             f"Fields right: {s['field_accuracy_pct']}% of {s['fields_checked']}   "
             f"readings fully right: {s['readings_all_correct']}/{s['readings']}",
             f"Cost: ${s['cost_usd']:.5f}   mean latency: {s['mean_latency_ms']} ms", ""]
    lines += [f"  {field:<20} {pct}%" for field, pct in s["per_field_pct"].items()]
    if result["misses"]:
        lines += ["", "Misses:"]
        lines += [f"  {m['id']}: {m['field']}  got {json.dumps(m['got'], ensure_ascii=False)}"
                  for m in result["misses"]]
    return "\n".join(lines)
