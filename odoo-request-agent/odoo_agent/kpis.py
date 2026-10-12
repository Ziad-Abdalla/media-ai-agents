"""KPIs for management: is the agent saving time and money, and is it right?

Everything is computed from data the agent already keeps: the runs table, the audit log and the
cost ledger. Nothing here calls the model or writes anything.

  python -m odoo_agent kpis          the same numbers as the /kpis page, as text
  python -m odoo_agent kpis --json   for a spreadsheet or another report

Definitions (also printed with the report, so nobody has to guess):
  auto-resolved     the agent matched vendor and production itself; the run went straight to
                    "waiting for approval"
  needed a human    a person had to pick the vendor or production, or confirm a re-send
  approval rate     approved / (approved + rejected), over runs a person decided
  success rate      finished runs that ended right without a fix: a draft PO that was not rolled
                    back, or a clarification reply sent. Rolled back, failed and write_failed
                    count as failures. Rejected runs are a person's decision, so they are left out.
  handling time     from the email's Date header to the draft PO being created in Odoo
  minutes saved     an estimate from the assumptions in config.py (MINUTES_*), not a measurement
"""

import json
from collections import Counter
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from statistics import median

from agent_cost_tracker import ledger

from . import config
from .budget import order_total_sar
from .models import PurchaseRequest

EXTRACT_OPERATION = "extract_purchase_request"
EVAL_RESULT = Path(__file__).resolve().parent.parent / "evals" / "last_run.json"


def parse_time(text: str | None) -> datetime | None:
    """Email dates come as ISO (Mailpit) or RFC 2822 (Gmail). Returns None if neither works."""
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            moment = parse(text)
            return moment if moment.tzinfo else None  # a time without a zone can't be compared
        except (TypeError, ValueError):
            pass
    return None


def _share(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def _minutes(seconds: list[float]) -> float | None:
    return round(median(seconds) / 60, 1) if seconds else None


def compute(store) -> dict:
    runs = store.list_runs()
    audit = store.all_audit_rows()
    status = Counter(r["status"] for r in runs)
    first = Counter(r["first_status"] for r in runs if r["first_status"])

    # Routes: what the agent could do on its own.
    planned = first["pending_approval"] + first["needs_human"]

    # Decisions by people.
    approved = {a["run_id"] for a in audit if a["operation"] == "approve"}
    decided = len(approved) + status["rejected"]

    # Success: ended right, without a fix.
    good = status["done"] + status["reply_sent"]
    bad = status["rolled_back"] + status["failed"] + status["write_failed"]

    # Time: email received -> draft PO created (and the agent's own part: received -> plan ready).
    po_created = {}
    for a in audit:
        if a["model"] == "purchase.order" and a["operation"] in ("create", "found_existing"):
            po_created.setdefault(a["run_id"], a["ts"])
    to_po, to_plan = [], []
    for r in runs:
        received = parse_time(r["received_at"])
        if not received:
            continue
        if r["run_id"] in po_created:
            to_po.append((parse_time(po_created[r["run_id"]]) - received).total_seconds())
        if r["planned_at"]:
            to_plan.append((parse_time(r["planned_at"]) - received).total_seconds())

    # Cost: model spend for these runs, from the shared ledger.
    conn = ledger.connect()
    spend = {row["run_id"]: row["cost"] for row in conn.execute(
        "SELECT run_id, SUM(cost_usd) AS cost FROM calls WHERE operation = ? GROUP BY run_id",
        (EXTRACT_OPERATION,))}
    conn.close()
    run_ids = {r["run_id"] for r in runs}
    model_runs = [rid for rid in spend if rid in run_ids]
    total_cost = sum(spend[rid] for rid in model_runs)

    # Time saved (an estimate; the assumptions are printed next to it).
    per_po = config.MINUTES_MANUAL_PO - config.MINUTES_REVIEW_PO
    minutes_saved = status["done"] * per_po + status["reply_sent"] * config.MINUTES_PER_REPLY

    # Money: draft POs the agent created, by production.
    by_production = Counter()
    for r in runs:
        if r["status"] == "done" and r["request_json"]:
            production = (r["resolution_json"] or {}).get("production") or {}
            name = production.get("name") or "(no production)"
            by_production[name] += order_total_sar(PurchaseRequest.model_validate(r["request_json"]))

    return {
        "runs_total": len(runs),
        "runs_by_status": dict(status.most_common()),
        "auto_resolved": first["pending_approval"],
        "needed_human": first["needs_human"],
        "auto_resolved_pct": _share(first["pending_approval"], planned),
        "needed_info": first["needs_info"],
        "blocked_senders": first["blocked_sender"],
        "approved": len(approved),
        "rejected": status["rejected"],
        "approval_rate_pct": _share(len(approved), decided),
        "succeeded": good,
        "failed_or_undone": bad,
        "success_rate_pct": _share(good, good + bad),
        "median_minutes_email_to_po": _minutes(to_po),
        "median_minutes_email_to_plan": _minutes(to_plan),
        "pos_timed": len(to_po),
        "model_cost_usd": round(total_cost, 5),
        "cost_per_request_usd": round(total_cost / len(model_runs), 5) if model_runs else None,
        "requests_read_by_model": len(model_runs),
        "minutes_saved_estimate": round(minutes_saved),
        "assumption": (f"by hand a PO takes {config.MINUTES_MANUAL_PO:g} min, checking the agent's "
                       f"plan {config.MINUTES_REVIEW_PO:g} min, so each draft PO saves {per_po:g} min; "
                       f"each drafted clarification reply saves {config.MINUTES_PER_REPLY:g} min"),
        "draft_po_sar_by_production": {k: round(v, 2) for k, v in by_production.most_common()},
        "extraction_eval": json.loads(EVAL_RESULT.read_text(encoding="utf-8"))["summary"]
                           if EVAL_RESULT.exists() else None,
    }


def as_text(k: dict) -> str:
    def show(value, unit=""):
        return "n/a" if value is None else f"{value}{unit}"

    lines = [
        "Purchase request agent: KPIs",
        "",
        f"Runs: {k['runs_total']}   " + ", ".join(f"{s} {n}" for s, n in k["runs_by_status"].items()),
        f"Auto-resolved: {k['auto_resolved']}   needed a human: {k['needed_human']}   "
        f"auto share: {show(k['auto_resolved_pct'], '%')}",
        f"Asked the sender for missing info: {k['needed_info']}   blocked outside senders: {k['blocked_senders']}",
        f"Approval rate: {show(k['approval_rate_pct'], '%')} ({k['approved']} approved, {k['rejected']} rejected)",
        f"Success rate: {show(k['success_rate_pct'], '%')} ({k['succeeded']} ended right, "
        f"{k['failed_or_undone']} failed or rolled back)",
        f"Median time, email -> draft PO: {show(k['median_minutes_email_to_po'], ' min')} "
        f"({k['pos_timed']} POs); email -> plan ready: {show(k['median_minutes_email_to_plan'], ' min')}",
        f"Model cost: ${k['model_cost_usd']:.5f} for {k['requests_read_by_model']} requests, "
        + ("n/a per request" if k["cost_per_request_usd"] is None
           else f"${k['cost_per_request_usd']:.5f} per request"),
        f"Estimated time saved: {k['minutes_saved_estimate']} min (assumption: {k['assumption']})",
    ]
    if k["draft_po_sar_by_production"]:
        lines += ["", "Draft POs created by the agent, by production (SAR, before VAT):"]
        lines += [f"  {name}: {amount:,.2f}" for name, amount in k["draft_po_sar_by_production"].items()]
    if k.get("budgets"):
        lines += ["", "Production budgets (committed = all open POs, drafts included):"]
        lines += [f"  {b['production']}: {b['committed']:,.0f} of {b['budget']:,.0f} SAR "
                  f"({b['used_pct']}%, {b['po_count']} POs)" for b in k["budgets"]]
    if k["extraction_eval"]:
        e = k["extraction_eval"]
        lines += ["", f"Extraction accuracy (last eval, {e['emails']} labelled synthetic emails): "
                      f"{e['field_accuracy_pct']}% of fields, {e['emails_all_correct']} emails fully right"]
    return "\n".join(lines)
