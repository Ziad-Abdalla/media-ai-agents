"""Step 6: the approval page (Arabic, right-to-left). Plain HTML forms, no JavaScript needed.

Start it with:  python -m inbox_agent serve   then open http://localhost:8010
Nothing is sent, forwarded or created on the task board until a person presses a button here.
Who is acting comes from a sign-in cookie (in a real deployment: the company's SSO). What that
person may approve comes from staff.yaml (can_approve) and is checked on the server.
"""

import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import Cookie, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import briefing, kpi, pipeline
from .briefing import ACTION_AR, CATEGORY_AR, PRIORITY_AR
from .store import plan_hash as hash_plan

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["pretty"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)
templates.env.filters["pct"] = kpi.fmt_pct
templates.env.globals.update(CATEGORY_AR=CATEGORY_AR, PRIORITY_AR=PRIORITY_AR, ACTION_AR=ACTION_AR,
                             plan_hash=hash_plan)
CATEGORY_ORDER = ["suspicious", "urgent_action", "approval_needed", "legal_contract", "vendor_finance",
                  "meeting", "info", "spam"]
STATUS_AR = {"pending": "بانتظار الاعتماد", "executed": "نُفّذ", "rejected": "مرفوض", "blocked": "محظور",
             "failed": "فشل", "rolled_back": "تم التراجع", "executing": "قيد التنفيذ",
             "proposed": "مقترح", "needs_confirmation": "يحتاج تأكيدًا", "confirmed": "مؤكَّد",
             "reassigned": "أُعيد إسناده"}
templates.env.globals["STATUS_AR"] = STATUS_AR


def safe_next(target: str | None) -> str:
    """Only redirect to a path on this site. "//evil.example", "https://...", a backslash
    trick and anything with a scheme or host fall back to "/" (no open redirect)."""
    t = (target or "").strip()
    if not t.startswith("/") or t.startswith("//") or t.startswith("/\\") or "\\" in t:
        return "/"
    parts = urlsplit(t)
    if parts.scheme or parts.netloc or any(ord(c) < 32 for c in t):
        return "/"
    return t


def create_app(ctx) -> FastAPI:
    app = FastAPI(title="Executive inbox agent")
    d = ctx.directory

    def page(request, name, user, **data):
        me = d.get(user)
        return templates.TemplateResponse(request, name, {
            "me": me, "people": list(d.people.values()), "approvers": d.approvers(),
            "directory": d, "pending_count": len(ctx.store.actions("status = 'pending'")), **data})

    def back(to: str, message: str) -> RedirectResponse:
        to = safe_next(to)
        sep = "&" if "?" in to else "?"
        return RedirectResponse(f"{to}{sep}message={quote(message)}", status_code=303)

    @app.post("/login")
    def login(user: str = Form(...), next: str = Form("/")):
        resp = RedirectResponse(safe_next(next), status_code=303)
        if d.get(user):
            resp.set_cookie("user", user, httponly=True, samesite="strict")
        return resp

    @app.get("/", response_class=HTMLResponse)
    def inbox(request: Request, category: str = "", message: str = "", user: str | None = Cookie(None)):
        emails = ctx.store.emails()
        if category:
            emails = [e for e in emails if e["category"] == category]
        threads: dict[str, dict] = {}
        for e in emails:
            t = threads.setdefault(e["thread_id"], {"thread": ctx.store.get_thread(e["thread_id"]),
                                                    "emails": []})
            t["emails"].append(e)
        for t in threads.values():
            t["last"] = t["emails"][-1]
            t["rank"] = min(CATEGORY_ORDER.index(e["category"]) if e["category"] in CATEGORY_ORDER else 99
                            for e in t["emails"])
            t["urgent"] = any(e["priority"] == "urgent" for e in t["emails"])
            t["open"] = sum(len(ctx.store.actions("email_id = ? AND status = 'pending'", (e["id"],)))
                            for e in t["emails"])
        ordered = sorted(threads.values(), key=lambda t: (t["rank"], not t["urgent"], t["last"]["date"]),
                         reverse=False)
        counts = {}
        for e in ctx.store.emails():
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        decisions = _pending_decisions(ctx)
        return page(request, "inbox.html", user, threads=ordered, counts=counts, category=category,
                    message=message, decisions=decisions, CATEGORY_ORDER=CATEGORY_ORDER)

    @app.get("/email/{email_id}", response_class=HTMLResponse)
    def email_page(request: Request, email_id: str, message: str = "", user: str | None = Cookie(None)):
        e = ctx.store.get_email(email_id)
        if not e:
            return back("/", "الرسالة غير موجودة")
        thread = ctx.store.emails("thread_id = ?", (e["thread_id"],))
        tasks = ctx.store.tasks("email_id = ?", (email_id,))
        for t in tasks:
            t["actions"] = ctx.store.actions("task_id = ?", (t["id"],))
        actions = ctx.store.actions("email_id = ? AND task_id IS NULL", (email_id,))
        audit = ctx.store.audit_rows("email_id = ?", (email_id,), limit=50)
        return page(request, "email.html", user, e=e, thread=thread, tasks=tasks, actions=actions,
                    audit=audit, message=message)

    def acting(user):
        if not d.get(user):
            raise PermissionError("سجّل الدخول باسمك أولًا")
        return user

    @app.post("/actions/{action_id}/approve")
    def approve(action_id: int, plan_hash: str = Form(""), next: str = Form("/"),
                user: str | None = Cookie(None)):
        try:
            pipeline.approve_action(ctx, action_id, acting(user), plan_hash)
        except (PermissionError, ValueError, OSError, *pipeline.ACTION_ERRORS) as e:
            return back(next, f"لم يُنفَّذ: {e}")
        return back(next, "تم الاعتماد والتنفيذ")

    @app.post("/actions/{action_id}/reject")
    def reject(action_id: int, next: str = Form("/"), user: str | None = Cookie(None)):
        try:
            pipeline.reject_action(ctx, action_id, acting(user))
        except (PermissionError, ValueError) as e:
            return back(next, f"لم يُرفض: {e}")
        return back(next, "تم الرفض")

    @app.post("/tasks/{task_id}/reassign")
    def reassign(task_id: int, new_owner: str = Form(...), reason: str = Form(""),
                 plan_hash: str = Form(""), next: str = Form("/"), user: str | None = Cookie(None)):
        try:
            who = acting(user)
            out = pipeline.reassign_task(ctx, task_id, new_owner, reason or "بدون سبب", who,
                                         plan_hash or None)
            if out.get("board") == "pending":   # the person chose the owner: create it now
                action = ctx.store.get_action(out["action_id"])
                pipeline.approve_action(ctx, action["id"], who, hash_plan(action["plan_json"]))
        except (PermissionError, ValueError, OSError, *pipeline.ACTION_ERRORS) as e:
            return back(next, f"لم تتم إعادة الإسناد: {e}")
        return back(next, f"أُسندت المهمة إلى {d.get(new_owner).name_ar} وسُجّل التصحيح")

    @app.post("/email/{email_id}/forward")
    def forward(email_id: str, to_person: str = Form(...), user: str | None = Cookie(None)):
        try:
            pipeline.propose_forward(ctx, email_id, to_person, acting(user))
        except (PermissionError, ValueError) as e:
            return back(f"/email/{email_id}", f"لم يُجهَّز التحويل: {e}")
        return back(f"/email/{email_id}", "جُهّز التحويل الداخلي، بانتظار الاعتماد")

    @app.post("/email/{email_id}/release")
    def release(email_id: str, user: str | None = Cookie(None)):
        try:
            pipeline.release_quarantine(ctx, email_id, acting(user))
        except (PermissionError, ValueError, *pipeline.ACTION_ERRORS) as e:
            return back(f"/email/{email_id}", f"لم يُفك الحجز: {e}")
        return back(f"/email/{email_id}", "تم فك الحجز")

    @app.post("/actions/{action_id}/rollback")
    def rollback(action_id: int, next: str = Form("/"), user: str | None = Cookie(None)):
        try:
            pipeline.rollback(ctx, action_id, acting(user))
        except (PermissionError, ValueError) as e:
            return back(next, f"لم يتم التراجع: {e}")
        return back(next, "تم التراجع")

    @app.get("/kpi", response_class=HTMLResponse)
    def kpi_page(request: Request, user: str | None = Cookie(None)):
        return page(request, "kpi.html", user, k=kpi.compute(ctx.store),
                    timeline=kpi.accuracy_over_time(ctx.store),
                    corrections=ctx.store.corrections(limit=20))

    @app.get("/audit", response_class=HTMLResponse)
    def audit_page(request: Request, user: str | None = Cookie(None)):
        return page(request, "audit.html", user, rows=ctx.store.audit_rows(limit=300))

    @app.get("/briefing", response_class=HTMLResponse)
    def briefing_page(as_of: str = ""):
        from datetime import date
        html, _ = briefing.render(ctx.store, d, as_of or date.today().isoformat())
        return HTMLResponse(html)

    return app


def _pending_decisions(ctx) -> list[dict]:
    out = []
    for a in ctx.store.actions("status = 'pending'"):
        e = ctx.store.get_email(a["email_id"])
        t = ctx.store.get_task(a["task_id"]) if a["task_id"] else None
        out.append({"a": a, "e": e, "t": t})
    # flagged ones first, then urgent
    out.sort(key=lambda x: (not (x["t"] and x["t"]["needs_confirmation"]),
                            (x["e"] or {}).get("priority") != "urgent"))
    return out
