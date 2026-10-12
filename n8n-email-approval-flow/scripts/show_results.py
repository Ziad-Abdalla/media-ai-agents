"""Print what the workflow did: the database tables, plus any approval links still waiting.

    python scripts/show_results.py
"""
import json
import re
import subprocess
import pathlib
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")  # Arabic subjects and names print on any Windows console

QUERIES = {
    "Emails seen (one row per Message-ID)": (
        "SELECT message_id, status, route, language AS lang, resource_code, clash FROM email_log ORDER BY received_at"),
    "Bookings": (
        "SELECT id, request_type, resource_code, quantity AS qty, start_date, end_date, production, "
        "requester_email, had_clash, odoo_sync FROM bookings ORDER BY id"),
    "Reply drafts (needs info)": "SELECT to_address, subject, body FROM reply_drafts ORDER BY id",
    "AI usage": "SELECT message_id, input_tokens, output_tokens, cost_usd, route FROM ai_usage ORDER BY id",
    "AI cost summary": (
        "SELECT count(*) AS claude_calls, sum(cost_usd) AS total_usd, round(avg(cost_usd), 6) AS avg_usd_per_email, "
        "(SELECT count(*) FROM bookings) AS bookings, "
        "round(sum(cost_usd) / NULLIF((SELECT count(*) FROM bookings), 0), 6) AS usd_per_booking FROM ai_usage"
    ),
    "KPIs, last 7 days (same view the weekly email uses)": (
        "SELECT booking_requests, auto_routed_pct, approval_rate_pct, median_minutes_to_decision, "
        "clashes_flagged, ai_cost_per_booking_usd, est_minutes_saved, errors FROM kpi_last_7_days"),
    "Weekly summaries sent": "SELECT id, sent_to, created_at FROM report_log ORDER BY id",
    "Workflow errors (with the email the failed run was handling, if any)": (
        "SELECT w.execution_id, w.failed_node, w.error_message, e.message_id, e.status "
        "FROM workflow_errors w LEFT JOIN email_log e ON e.execution_id = w.execution_id ORDER BY w.id"
    ),
}


def psql(sql):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "bookings", "-d", "bookings_app", "-c", sql],
        cwd=ROOT, capture_output=True, text=True, encoding="utf8")
    return out.stdout or out.stderr


def pending_links():
    url = "http://localhost:8026/api/v1/search?query=" + urllib.parse.quote("to:ops-manager@sadafprod.test")
    msgs = json.loads(urllib.request.urlopen(url).read())["messages"]
    for m in reversed(msgs):
        full = json.loads(urllib.request.urlopen(f"http://localhost:8026/api/v1/message/{m['ID']}").read())
        # Only read our own part of the email, not the quoted original (it could contain fake links).
        ours = full["Text"].split("----- Original email")[0]
        links = re.findall(r"(APPROVE|REJECT):\s+(\S+)", ours)
        print(f"- {m['Subject']}")
        for label, link in links:
            print(f"    {label}: {link}")


if __name__ == "__main__":
    for title, sql in QUERIES.items():
        print(f"== {title}")
        print(psql(sql))
    print("== Approval emails sent to the manager (links work once; used links do nothing)")
    pending_links()
