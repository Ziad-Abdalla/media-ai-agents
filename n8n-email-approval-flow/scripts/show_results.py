"""Print what the workflow did: the database tables, plus any approval links still waiting.

    python scripts/show_results.py
"""
import json
import re
import subprocess
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent

QUERIES = {
    "Emails seen (one row per Message-ID)": "SELECT message_id, from_address, status FROM email_log ORDER BY received_at",
    "Bookings": "SELECT id, request_type, item, start_date, end_date, production, requester_email FROM bookings ORDER BY id",
    "Reply drafts (needs info)": "SELECT to_address, subject, body FROM reply_drafts ORDER BY id",
    "AI usage": "SELECT message_id, input_tokens, output_tokens, cost_usd, route FROM ai_usage ORDER BY id",
    "AI cost summary": (
        "SELECT count(*) AS claude_calls, sum(cost_usd) AS total_usd, round(avg(cost_usd), 6) AS avg_usd_per_email, "
        "(SELECT count(*) FROM bookings) AS bookings, "
        "round(sum(cost_usd) / NULLIF((SELECT count(*) FROM bookings), 0), 6) AS usd_per_booking FROM ai_usage"
    ),
    "Workflow errors": "SELECT workflow_name, execution_id, failed_node, error_message FROM workflow_errors ORDER BY id",
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
        links = re.findall(r"(APPROVE|REJECT):\s+(\S+)", full["Text"])
        print(f"- {m['Subject']}")
        for label, link in links:
            print(f"    {label}: {link}")


if __name__ == "__main__":
    import urllib.parse
    for title, sql in QUERIES.items():
        print(f"== {title}")
        print(psql(sql))
    print("== Approval emails sent to the manager (links work once; used links do nothing)")
    pending_links()
