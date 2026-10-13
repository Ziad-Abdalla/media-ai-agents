"""Make the demo's human decisions with a script, through the same web forms a person uses.

  python scripts/demo_decisions.py

This is for the README demo only. It approves, rejects, picks and rolls back in a few seconds,
so the KPI "waiting for a person" time it leaves behind measures nothing about real reviewers.
The audit log records the actor as "demo-script", never as a person's name.

What it decides, by sample id (samples/requests.json):
  crane, sound-injection, arabic-lights, mixed-camera, crew-freelancer, location-fee   approve
  lights-incomplete      send the drafted "please send the missing details" reply
  crane-resent           reject (it is a re-send)
  catering-new-vendor    approve, then roll it back (a rollback drill)
  led-wall-over-budget   approve without a reason (refused), then with a reason
  unclear-production     pick Rimal Al-Khobar, then approve
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from odoo_agent.odoo_client import OdooClient  # noqa: E402
from odoo_agent.rollback import rollback  # noqa: E402
from odoo_agent.store import Store  # noqa: E402
from odoo_agent.web import create_app  # noqa: E402

ACTOR = "demo-script"
SAMPLES = json.loads((ROOT / "samples" / "requests.json").read_text(encoding="utf-8"))["samples"]
SAMPLE_BY_SUBJECT = {s["subject"]: s["id"] for s in SAMPLES}


def shown_hash(web, run_id):
    """The plan hash on the page, as a person's browser would send it back."""
    page = web.get(f"/?run={run_id}").text
    return re.search(r'name="plan_hash" value="([0-9a-f]{64})"', page).group(1)


def say(response):
    message = response.headers.get("location", "").split("message=", 1)[-1]
    print("   ", unquote(message))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    store = Store()
    web = TestClient(create_app(store, OdooClient), follow_redirects=False)
    runs = {SAMPLE_BY_SUBJECT.get(r["subject"]): r for r in store.list_runs()}

    def approve(sample_id, **extra):
        run_id = runs[sample_id]["run_id"]
        print(f"{sample_id}: approve {extra or ''}")
        say(web.post(f"/runs/{run_id}/approve",
                     data={"approver": ACTOR, "plan_hash": shown_hash(web, run_id), **extra}))

    for sample_id in ["crane", "sound-injection", "catering-new-vendor", "arabic-lights", "mixed-camera",
                      "crew-freelancer", "location-fee"]:
        approve(sample_id)

    print("lights-incomplete: send the drafted reply")
    say(web.post(f"/runs/{runs['lights-incomplete']['run_id']}/send_reply", data={"approver": ACTOR}))

    print("crane-resent: reject")
    say(web.post(f"/runs/{runs['crane-resent']['run_id']}/reject", data={"approver": ACTOR}))

    approve("led-wall-over-budget")  # no reason: refused and audited
    approve("led-wall-over-budget", over_budget_ok="yes",
            over_budget_reason="Season opener needs the LED wall; line producer agreed (demo text)")

    unclear = runs["unclear-production"]
    rimal = next(c for c in unclear["resolution_json"]["production"]["candidates"] if c.get("code") == "RML-S1")
    print("unclear-production: pick Rimal Al-Khobar")
    say(web.post(f"/runs/{unclear['run_id']}/resolve", data={"approver": ACTOR, "production": str(rimal["id"])}))
    approve("unclear-production")

    print("catering-new-vendor: rollback drill")
    for line in rollback(store, OdooClient(), runs["catering-new-vendor"]["run_id"], actor=f"human:{ACTOR}"):
        print("   ", line)


if __name__ == "__main__":
    main()
