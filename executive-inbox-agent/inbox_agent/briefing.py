"""Step 8: the morning executive briefing, in Arabic, built from the database.

No model writes this page: it is a template filled with facts the agent already stored
(summaries, deadlines, pending approvals), so the numbers can't drift. It's saved as HTML
and sent through permissions.execute("send_briefing"), which only allows the one internal
executive address (DLP), so it can't be pointed anywhere else.
"""

from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, kpi
from .permissions import execute

CATEGORY_AR = {"urgent_action": "إجراء عاجل", "approval_needed": "بحاجة لاعتماد", "meeting": "اجتماع",
               "info": "للعلم", "vendor_finance": "موردون ومالية", "legal_contract": "قانوني وعقود",
               "spam": "دعائية", "suspicious": "مشبوهة"}
PRIORITY_AR = {"urgent": "عاجل جدًا", "high": "مرتفعة", "normal": "عادية", "low": "منخفضة"}
ACTION_AR = {"send_reply": "إرسال رد", "forward_internal": "تحويل داخلي", "create_task": "إنشاء مهمة",
             "reassign_task": "إعادة إسناد", "release_quarantine": "فك الحجز"}
WEEKDAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

env = Environment(loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
                  autoescape=select_autoescape(["html"]))


def gather(store, directory, as_of: str) -> dict:
    today = date.fromisoformat(as_of[:10])
    week_end = (today + timedelta(days=7)).isoformat()
    emails = {e["id"]: e for e in store.emails()}

    def person(pid):
        p = directory.get(pid)
        return f"{p.name_ar} ({p.role_ar})" if p else "—"

    urgent = []
    for e in emails.values():
        if e["status"] == "triaged" and e["priority"] == "urgent":
            open_tasks = store.tasks("email_id = ? AND status NOT IN ('rejected')", (e["id"],))
            urgent.append({"email": e, "tasks": [{**t, "owner": person(t["final_owner"] or t["proposed_owner"])}
                                                  for t in open_tasks]})
    pending = []
    for a in store.actions("status = 'pending'"):
        e = emails.get(a["email_id"], {})
        task = store.get_task(a["task_id"]) if a["task_id"] else None
        pending.append({"kind": ACTION_AR.get(a["kind"], a["kind"]), "subject": e.get("subject", ""),
                        "from": e.get("from_addr", ""), "id": a["id"],
                        "detail": (task["what_ar"] if task else a["plan_json"].get("subject", "")),
                        "owner": person(a["plan_json"].get("owner")) if a["kind"] == "create_task" else "",
                        "flagged": bool(task and task["needs_confirmation"])})
    deadlines = []
    for t in store.tasks("deadline IS NOT NULL AND deadline >= ? AND deadline <= ? AND status != 'rejected'",
                         (today.isoformat(), week_end)):
        d = date.fromisoformat(t["deadline"])
        deadlines.append({**t, "day": f"{WEEKDAYS_AR[d.weekday()]} {d.isoformat()}",
                          "owner": person(t["final_owner"] or t["proposed_owner"]),
                          "subject": emails[t["email_id"]]["subject"]})
    deadlines.sort(key=lambda t: t["deadline"])
    quarantined = [e for e in emails.values() if e["status"] == "quarantined"]
    counts = {}
    for e in emails.values():
        if e["category"]:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
    return {"as_of": today.isoformat(), "weekday": WEEKDAYS_AR[today.weekday()],
            "urgent": urgent, "pending": pending, "deadlines": deadlines, "quarantined": quarantined,
            "counts": sorted(counts.items(), key=lambda kv: -kv[1]), "kpi": kpi.compute(store),
            "CATEGORY_AR": CATEGORY_AR, "PRIORITY_AR": PRIORITY_AR,
            "company": directory.company["name_ar"]}


def render(store, directory, as_of: str) -> tuple[str, str]:
    """(html, plain text) for the briefing."""
    data = gather(store, directory, as_of)
    html = env.get_template("briefing.html").render(**data)
    k = data["kpi"]
    text = (f"الموجز التنفيذي الصباحي - {data['as_of']}\n"
            f"عاجل: {len(data['urgent'])} | بانتظار اعتمادكم: {len(data['pending'])} | "
            f"مواعيد هذا الأسبوع: {len(data['deadlines'])} | رسائل محجوزة: {len(data['quarantined'])}\n"
            f"الرسائل المعالجة: {k['emails_processed']} | الوقت الموفر تقديريًا: {k['minutes_saved_estimate']} دقيقة\n"
            "النسخة الكاملة في صيغة HTML.")
    return html, text


def build_and_send(ctx, as_of: str, send: bool = True) -> Path:
    html, text = render(ctx.store, ctx.directory, as_of)
    out = config.ROOT / "out" / f"briefing-{as_of[:10]}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    if send:
        execute("send_briefing", {"to": [ctx.directory.company["executive_briefing_to"]],
                                  "subject": f"الموجز التنفيذي الصباحي - {as_of[:10]}",
                                  "text": text, "html": html}, ctx=ctx)
    return out
