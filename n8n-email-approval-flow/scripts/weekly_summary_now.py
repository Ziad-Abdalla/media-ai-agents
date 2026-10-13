"""Send the weekly Arabic summary right now, instead of waiting for Sunday 08:00.

    python scripts/weekly_summary_now.py

It runs the "Weekly bookings summary" workflow once through the n8n command line. The email goes to
production-manager@sadafprod.test in Mailpit (http://localhost:8026), and a copy of the numbers is
saved in the report_log table.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The running n8n already uses port 5679 for its task runners, so this one-off run uses another.
cmd = ["docker", "compose", "exec", "-T", "-e", "N8N_RUNNERS_BROKER_PORT=5690",
       "n8n", "n8n", "execute", "--id=BookingWeekly001"]
out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf8")
# The command prints the whole run as JSON after some log lines; we only need its status.
start = out.stdout.find("{")
try:
    status = json.loads(out.stdout[start:])["status"] if start >= 0 else "unknown"
except json.JSONDecodeError:
    status = "unknown"
if status != "success":
    sys.exit(f"weekly summary failed ({status}):\n{out.stdout[-2000:]}{out.stderr[-2000:]}")
print("weekly summary sent to production-manager@sadafprod.test (see http://localhost:8026)")
