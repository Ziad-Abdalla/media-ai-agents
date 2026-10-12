"""Step 5: the approval page. One page, plain HTML forms, no JavaScript.

Start it with:  python -m odoo_agent serve   then open http://localhost:8000
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

from . import pipeline
from .permissions import ForbiddenAction, WritesDisabled, execute

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["pretty"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)
STATUS_ORDER = ["pending_approval", "needs_human", "write_failed", "needs_info",
                "done", "failed", "blocked_sender", "rejected", "rolled_back"]


def create_app(store, get_odoo) -> FastAPI:
    """get_odoo is a function so the page can load even if Odoo is down."""
    app = FastAPI(title="Purchase request approvals")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, message: str = "", run: str = ""):
        runs = [r for r in [store.get_run(run)] if r] if run else store.list_runs()  # ?run=<id>: one run
        runs.sort(key=lambda r: STATUS_ORDER.index(r["status"]) if r["status"] in STATUS_ORDER else 99)
        conn = ledger.connect()
        for run in runs:
            run["cost_usd"] = ledger.run_spend(conn, run["run_id"])
        conn.close()
        return templates.TemplateResponse(request, "index.html", {"runs": runs, "message": message})

    def back(message: str) -> RedirectResponse:
        return RedirectResponse(f"/?message={quote(message)}", status_code=303)

    @app.post("/runs/{run_id}/approve")
    def approve(run_id: str, approver: str = Form(...)):
        try:
            po_id = pipeline.approve_run(store, get_odoo(), run_id, approver)
        except (WritesDisabled, ForbiddenAction, ValueError, OSError, xmlrpc.client.Error) as e:
            return back(f"Not written: {e}")
        return back(f"{run_id} approved by {approver}: draft PO id {po_id} created")

    @app.post("/runs/{run_id}/reject")
    def reject(run_id: str, approver: str = Form(...)):
        pipeline.reject_run(store, run_id, approver)
        return back(f"{run_id} rejected by {approver}")

    @app.post("/runs/{run_id}/choose_vendor")
    def choose_vendor(run_id: str, partner: str = Form(...)):
        # partner is "<id>|<name>", or "new" to create a vendor, or "keep" (re-send confirmed)
        if partner in ("new", "keep"):
            pipeline.choose_vendor(store, run_id, None)
        else:
            pid, name = partner.split("|", 1)
            pipeline.choose_vendor(store, run_id, int(pid), name)
        return back(f"{run_id}: ready for approval")

    @app.post("/runs/{run_id}/send_reply")
    def send_reply(run_id: str, approver: str = Form(...)):
        run = store.get_run(run_id)
        try:
            execute("send_email", odoo=None, store=store, run_id=run_id, approved_by=approver,
                    to=run["sender"], subject="Re: " + run["subject"], body=run["reply_draft"])
        except (WritesDisabled, ForbiddenAction, OSError) as e:
            return back(f"Not sent: {e}")
        return back(f"Reply sent to {run['sender']}")

    return app
