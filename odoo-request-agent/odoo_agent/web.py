"""Step 5: the approval page, plus a KPI page. Plain HTML forms, no JavaScript.

Start it with:  python -m odoo_agent serve   then open http://localhost:8000 (and /kpis)
Nothing is written to Odoo until someone presses Approve here.
(A real deployment would sit behind the company login; here the approver types a name.)
"""

import json
import xmlrpc.client
from pathlib import Path
from urllib.parse import quote

from agent_cost_tracker import ledger
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import budget, kpis, pipeline
from .permissions import ForbiddenAction, WritesDisabled, execute

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["pretty"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)
OPEN = ("pending_approval", "needs_human", "write_failed")  # runs still waiting on a person
STATUS_ORDER = ["pending_approval", "needs_human", "write_failed", "needs_info",
                "done", "reply_sent", "failed", "blocked_sender", "rejected", "rolled_back"]


def create_app(store, get_odoo) -> FastAPI:
    """get_odoo is a function so the page can load even if Odoo is down."""
    app = FastAPI(title="Purchase request approvals")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, message: str = "", run: str = ""):
        if run:  # ?run=<id> shows just that one run
            one = store.get_run(run)
            runs = [one] if one else []
        else:
            runs = store.list_runs()
        runs.sort(key=lambda r: STATUS_ORDER.index(r["status"]) if r["status"] in STATUS_ORDER else 99)
        conn = ledger.connect()
        for r in runs:
            r["cost_usd"] = ledger.run_spend(conn, r["run_id"])
            r["plan_hash"] = pipeline.plan_hash(r["plan_json"])  # goes back with the Approve click
        conn.close()
        budget_error = add_budgets([r for r in runs if r["status"] in OPEN])
        return templates.TemplateResponse(request, "index.html", {
            "runs": runs, "message": message, "budget_error": budget_error})

    def add_budgets(runs) -> str:
        """Fresh budget numbers for the runs still waiting on someone. Needs Odoo; if Odoo is
        down the page still loads, says so, and Approve re-checks anyway."""
        if not runs:
            return ""
        try:
            odoo = get_odoo()
            for r in runs:
                r["budget"] = budget.check_run(odoo, r)
        except (OSError, xmlrpc.client.Error, PermissionError) as e:
            return f"Budget check unavailable (Odoo not reachable: {e}). Approve checks it again."
        return ""

    @app.get("/kpis", response_class=HTMLResponse)
    def kpi_page(request: Request):
        report = kpis.compute(store)
        try:
            report["budgets"] = budget.production_overview(get_odoo())
        except (OSError, xmlrpc.client.Error, PermissionError) as e:
            report["budgets_error"] = f"Odoo not reachable: {e}"
        return templates.TemplateResponse(request, "kpis.html", {"k": report})

    def back(message: str) -> RedirectResponse:
        return RedirectResponse(f"/?message={quote(message)}", status_code=303)

    @app.post("/runs/{run_id}/approve")
    def approve(run_id: str, approver: str = Form(...), plan_hash: str = Form(""),
                over_budget_ok: str = Form(""), over_budget_reason: str = Form("")):
        # plan_hash is the hash of the plan this person saw. A missing one is refused.
        # The reason only counts if the "approve over budget" box was ticked too.
        reason = over_budget_reason if over_budget_ok else ""
        try:
            po_id = pipeline.approve_run(store, get_odoo(), run_id, approver, plan_hash, reason)
        except (WritesDisabled, ForbiddenAction, ValueError, OSError, xmlrpc.client.Error) as e:
            return back(f"Not written: {e}")
        return back(f"{run_id} approved by {approver}: draft PO id {po_id} created")

    @app.post("/runs/{run_id}/reject")
    def reject(run_id: str, approver: str = Form(...)):
        try:
            pipeline.reject_run(store, run_id, approver)
        except ValueError as e:
            return back(f"Not rejected: {e}")
        return back(f"{run_id} rejected by {approver}")

    @app.post("/runs/{run_id}/resolve")
    def resolve(run_id: str, approver: str = Form(...), partner: str = Form(""),
                production: str = Form("")):
        # The answer to a needs_human question. partner is empty (no vendor question) or:
        #   "<id>|<name>"     the person picked this vendor
        #   "new"             none of these: create a new vendor
        #   "confirm_resend"  yes, this re-send really is a second order
        # production is empty (no production question) or the id of the chosen production.
        try:
            if not approver.strip():
                raise ValueError("type your name")
            choice = {"new_vendor": partner == "new", "chosen_by": approver.strip(),
                      "production_id": int(production) if production else None}
            if partner and partner not in ("new", "confirm_resend"):
                pid, name = partner.split("|", 1)
                pipeline.resolve_needs_human(store, run_id, int(pid), name, **choice)
            else:
                pipeline.resolve_needs_human(store, run_id, **choice)
        except ValueError as e:
            return back(f"Not changed: {e}")
        return back(f"{run_id}: ready for approval")

    @app.post("/runs/{run_id}/send_reply")
    def send_reply(run_id: str, approver: str = Form(...)):
        run = store.get_run(run_id)
        approver = approver.strip()
        if not approver or not run or run["status"] != "needs_info" or not run["reply_draft"]:
            return back(f"Not sent: {run_id} has no unsent reply (or no name was typed)")
        try:
            execute("send_email", odoo=None, store=store, run_id=run_id, approved_by=approver,
                    to=run["sender"], subject="Re: " + run["subject"], body=run["reply_draft"])
        except (WritesDisabled, ForbiddenAction, OSError) as e:
            return back(f"Not sent: {e}")
        store.update_run(run_id, status="reply_sent", approved_by=approver)  # so it's sent once
        return back(f"Reply sent to {run['sender']}")

    return app
