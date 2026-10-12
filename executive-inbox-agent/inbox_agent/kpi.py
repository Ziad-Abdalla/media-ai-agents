"""KPIs for executive management. All numbers come from the agent's own database and the
cost ledger; no model is involved, so nothing here can be invented.

Time saved is an ESTIMATE with a stated assumption (MANUAL_TRIAGE_MINUTES, default 3):
  - by hand, each email costs a person ~3 minutes: read it, decide who handles it, forward
    it, note the deadline.
  - with the agent: an email it fully handles (FYI, newsletter, spam) costs ~0.25 min (a glance
    at the label); an email that needs a decision costs ~1 min (read the Arabic summary, check
    the evidence, one click); a quarantined email costs the same 3 min (IT looks at it).
"""

import json
from pathlib import Path

from agent_cost_tracker import ledger

from . import config

AUTO_MINUTES, DECISION_MINUTES = 0.25, 1.0


def compute(store, eval_results_path: str | None = None) -> dict:
    emails = store.emails()
    n = len(emails)
    actions = store.actions()
    tasks = store.tasks()
    needs_person = {a["email_id"] for a in actions} | {t["email_id"] for t in tasks}
    quarantined = [e for e in emails if e["status"] in ("quarantined", "released")]
    errors = [e for e in emails if e["status"] == "error"]
    auto = [e for e in emails if e["status"] == "triaged" and e["id"] not in needs_person]
    human_done = {a["email_id"] for a in actions if a["status"] in ("executed", "rejected")} | \
                 {t["email_id"] for t in tasks if t["status"] in ("confirmed", "reassigned", "rejected")}

    decided = [t for t in tasks if t["status"] in ("confirmed", "reassigned")]
    kept = [t for t in decided if t["status"] == "confirmed"]
    approved = [a for a in actions if a["approved_by"] and a["status"] != "rejected"]
    succeeded = [a for a in approved if a["status"] in ("executed", "rolled_back")]

    manual = config.MANUAL_TRIAGE_MINUTES
    with_agent = (len(auto) * AUTO_MINUTES + (n - len(auto) - len(quarantined)) * DECISION_MINUTES
                  + len(quarantined) * manual)

    conn = ledger.connect()
    try:
        costs = [ledger.run_spend(conn, e["run_id"]) for e in emails if e["run_id"]]
    finally:
        conn.close()

    blocked = store.query("SELECT COUNT(*) AS c FROM audit WHERE outcome = 'blocked'")[0]["c"]
    out = {
        "emails_processed": n,
        "auto_handled": len(auto),
        "auto_handled_share": _share(len(auto), n),
        "needs_person": n - len(auto),
        "human_confirmed_emails": len(human_done),
        "human_confirmed_share": _share(len(human_done), n),
        "quarantined": len(quarantined),
        "errors": len(errors),
        "tasks_extracted": len(tasks),
        "tasks_flagged_for_confirmation": sum(1 for t in tasks if t["needs_confirmation"]),
        "assignments_decided": len(decided),
        "assignment_accuracy_live": _share(len(kept), len(decided)),
        "corrections": len(store.corrections()),
        "approved_actions": len(approved),
        "task_success_rate": _share(len(succeeded), len(approved)),
        "blocked_attempts": blocked,
        "manual_minutes_assumption": manual,
        "minutes_by_hand": round(n * manual, 1),
        "minutes_with_agent": round(with_agent, 1),
        "minutes_saved_estimate": round(n * manual - with_agent, 1),
        "total_cost_usd": round(sum(costs), 5),
        "cost_per_email_usd": round(sum(costs) / len(costs), 5) if costs else 0.0,
    }
    gold = latest_eval(eval_results_path)
    if gold:
        out["eval"] = gold
    return out


def accuracy_over_time(store) -> list[dict]:
    """Per day: how many proposed owners people kept vs changed."""
    rows = store.query("SELECT substr(decided_at, 1, 10) AS day, status, COUNT(*) AS c FROM tasks "
                       "WHERE status IN ('confirmed','reassigned') GROUP BY day, status ORDER BY day")
    days: dict[str, dict] = {}
    for r in rows:
        d = days.setdefault(r["day"], {"day": r["day"], "kept": 0, "changed": 0})
        d["kept" if r["status"] == "confirmed" else "changed"] += r["c"]
    for d in days.values():
        d["accuracy"] = _share(d["kept"], d["kept"] + d["changed"])
    return list(days.values())


def latest_eval(path: str | None = None) -> dict | None:
    p = Path(path) if path else config.ROOT / "eval" / "results" / "latest.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("scores")


def _share(a: int, b: int) -> float:
    return round(a / b, 3) if b else 0.0


def fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"

