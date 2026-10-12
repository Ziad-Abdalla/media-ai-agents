"""Command line.

  python -m odoo_agent poll [--gmail]   read new emails and prepare runs (no Odoo writes)
  python -m odoo_agent serve            start the approval page on http://localhost:8000 (KPIs on /kpis)
  python -m odoo_agent runs             list runs and their status
  python -m odoo_agent audit <run_id>   show the audit log of one run
  python -m odoo_agent rollback <run_id>
  python -m odoo_agent kill | unkill    stop / allow all agent writes
  python -m odoo_agent kpis [--json]    KPI report for management (no AI calls, no writes)
  python -m odoo_agent eval [--effort low|medium]   extraction accuracy on labelled emails
"""

import argparse
import pathlib
import sys

from . import config
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="odoo_agent")
    sub = parser.add_subparsers(dest="command", required=True)
    poll = sub.add_parser("poll")
    poll.add_argument("--gmail", action="store_true", help="read Gmail instead of Mailpit")
    sub.add_parser("serve")
    sub.add_parser("runs")
    sub.add_parser("audit").add_argument("run_id")
    sub.add_parser("rollback").add_argument("run_id")
    sub.add_parser("kill")
    sub.add_parser("unkill")
    sub.add_parser("kpis").add_argument("--json", action="store_true")
    sub.add_parser("eval").add_argument("--effort", default="low", choices=["low", "medium", "high"])
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # so Arabic subjects print on Windows
    store = Store()

    if args.command == "poll":
        import anthropic
        from agent_cost_tracker import BudgetExceeded

        from .inbox import GmailInbox, MailpitInbox, build_gmail_service
        from .odoo_client import OdooClient
        from .pipeline import process_email

        inbox = GmailInbox(build_gmail_service()) if args.gmail else MailpitInbox()
        client, odoo = anthropic.Anthropic(), OdooClient()
        for email in inbox.fetch():
            try:
                run_id = process_email(email, client=client, odoo=odoo, store=store)
            except BudgetExceeded as e:
                print(f"Stopped: {e}")
                break
            if run_id:
                run = store.get_run(run_id)
                production = ((run["resolution_json"] or {}).get("production") or {}).get("name", "")
                print(f"{run_id}  {run['status']:<16}  {email.subject}  {production}")

    elif args.command == "serve":
        import uvicorn

        from .odoo_client import OdooClient
        from .web import create_app

        uvicorn.run(create_app(store, OdooClient), host="127.0.0.1", port=8000)

    elif args.command == "runs":
        for r in store.list_runs():
            print(f"{r['run_id']}  {r['status']:<16}  po={r['po_id'] or '-':<5}  {r['subject']}")

    elif args.command == "audit":
        for row in store.audit_rows(args.run_id):
            print(row["ts"], row["actor"], row["operation"], row["model"] or "",
                  row["record_id"] or "", row["before"] or "", "->", row["after"] or "")

    elif args.command == "rollback":
        from .odoo_client import OdooClient
        from .rollback import rollback

        for line in rollback(store, OdooClient(), args.run_id):
            print(line)
        print(f"{args.run_id} rolled back")

    elif args.command == "kill":
        pathlib.Path(config.KILL_SWITCH_FILE).write_text("writes disabled\n")
        print(f"Kill switch ON ({config.KILL_SWITCH_FILE}). The agent will not write anything.")

    elif args.command == "unkill":
        pathlib.Path(config.KILL_SWITCH_FILE).unlink(missing_ok=True)
        print("Kill switch OFF.")

    elif args.command == "kpis":
        import json
        import xmlrpc.client

        from .budget import production_overview
        from .kpis import as_text, compute
        from .odoo_client import OdooClient

        report = compute(store)
        try:
            report["budgets"] = production_overview(OdooClient())
        except (OSError, xmlrpc.client.Error, PermissionError) as e:
            report["budgets_error"] = str(e)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else as_text(report))

    elif args.command == "eval":
        import anthropic

        from .evaluate import as_text, run_eval, save

        result = run_eval(anthropic.Anthropic(), effort=args.effort)
        print(as_text(result))
        print(f"\nSaved: {save(result)}")


if __name__ == "__main__":
    main()
