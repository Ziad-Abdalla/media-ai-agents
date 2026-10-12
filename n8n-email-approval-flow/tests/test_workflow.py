"""Checks on the exported workflow files. They read the JSON only: no Docker, no API calls.

    python -m unittest discover tests

n8n has no unit tests for a workflow, so these guard the rules that are easy to break
by accident when you edit a node in the editor and export again.
"""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf8"))


MAIN = load("workflows/booking-requests.json")
ERRORS = load("workflows/booking-errors.json")
WEEKLY = load("workflows/weekly-summary.json")
ALL = (MAIN, ERRORS, WEEKLY)
NODES = {n["name"]: n for n in MAIN["nodes"]}
WEEKLY_NODES = {n["name"]: n for n in WEEKLY["nodes"]}


def into(workflow, target):
    """Names of the nodes with a line into `target`."""
    return [src for src, out in workflow["connections"].items()
            for branch in out["main"] for link in branch if link["node"] == target]


class WorkflowRules(unittest.TestCase):
    def test_failures_go_to_the_error_workflow(self):
        self.assertEqual(MAIN["settings"]["errorWorkflow"], ERRORS["id"])
        self.assertEqual(WEEKLY["settings"]["errorWorkflow"], ERRORS["id"])

    def test_every_credential_is_in_the_template(self):
        template_ids = {c["id"] for c in load("credentials/credentials.template.json")}
        for wf in ALL:
            for node in wf["nodes"]:
                for cred in node.get("credentials", {}).values():
                    self.assertIn(cred["id"], template_ids, node["name"])

    def test_sql_values_are_passed_as_one_list(self):
        # The comma bug: the comma-separated box splits "crane (jib, 30 ft)" in two.
        # And a query with $1, $2... must get its values from that list, never pasted into the SQL.
        for wf in ALL:
            for node in wf["nodes"]:
                if node["type"] == "n8n-nodes-base.postgres":
                    query = node["parameters"]["query"]
                    self.assertNotIn("{{", query, node["name"])
                    values = node["parameters"]["options"].get("queryReplacement")
                    if "$1" in query:
                        self.assertTrue(values and values.startswith("={{ ["), node["name"])

    def test_webhook_needs_a_login(self):
        self.assertEqual(NODES["New email arrived"]["parameters"]["authentication"], "basicAuth")

    def test_approve_needs_the_approve_token(self):
        email = NODES["Write approval email"]["parameters"]["jsCode"]
        self.assertIn("&decision=approve&t=${r.approve_token}", email)
        self.assertIn("&decision=reject&t=${r.reject_token}", email)
        check = NODES["Approved?"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
        self.assertIn("approve_token", check)

    def test_duplicate_guard_still_outputs_on_conflict(self):
        # Without this, a duplicate returns zero items and "First time we see it?" never runs.
        self.assertTrue(NODES["Claim Message-ID"].get("alwaysOutputData"))

    def test_only_one_path_into_bookings(self):
        writers = [n["name"] for n in MAIN["nodes"] if "INSERT INTO bookings" in n["parameters"].get("query", "")]
        self.assertEqual(writers, ["Save booking"])
        self.assertEqual(into(MAIN, "Save booking"), ["Approved?"])

    def test_clash_check_runs_before_the_approval_email(self):
        self.assertEqual(into(MAIN, "Write approval email"), ["Check for clashes"])
        self.assertEqual(into(MAIN, "Check for clashes"), ["Route by result"])
        # No catalogue match returns no row; the email must still go out.
        self.assertTrue(NODES["Check for clashes"].get("alwaysOutputData"))

    def test_odoo_only_after_approval_and_only_when_switched_on(self):
        self.assertEqual(into(MAIN, "Add booking to Odoo"), ["Send to Odoo?"])
        self.assertEqual(into(MAIN, "Send to Odoo?"), ["Save booking"])
        switch = NODES["Send to Odoo?"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
        self.assertIn("odoo_sync_on === true", switch)
        init_sql = (ROOT / "db/init.sql").read_text(encoding="utf8")
        self.assertIn("('odoo_sync', 'off')", init_sql)

    def test_odoo_failure_does_not_stop_the_confirmation(self):
        self.assertEqual(NODES["Add booking to Odoo"].get("onError"), "continueErrorOutput")
        outputs = MAIN["connections"]["Add booking to Odoo"]["main"]
        self.assertEqual([[l["node"] for l in b] for b in outputs], [["Save Odoo id"], ["Note Odoo failure"]])
        self.assertEqual(sorted(into(MAIN, "Sender is internal?")),
                         ["Note Odoo failure", "Save Odoo id", "Send to Odoo?"])

    def test_confirmation_goes_to_the_header_address(self):
        to = NODES["Send confirmation"]["parameters"]["toEmail"]
        self.assertEqual(to, "={{ $('Check AI answer').first().json.from_address }}")

    def test_weekly_summary_only_goes_to_the_internal_manager(self):
        self.assertEqual(WEEKLY_NODES["Every Sunday 08:00"]["type"], "n8n-nodes-base.scheduleTrigger")
        emails = [n for n in WEEKLY["nodes"] if n["type"] == "n8n-nodes-base.emailSend"]
        self.assertEqual([e["parameters"]["toEmail"] for e in emails], ["production-manager@sadafprod.test"])

    def test_claude_call_settings(self):
        body = NODES["Ask Claude to extract"]["parameters"]["jsonBody"]
        self.assertIn('"model": "claude-haiku-5-5"', body)
        self.assertIn('"type": "json_schema"', body)
        for unsupported in ("temperature", "top_p", "budget_tokens"):
            self.assertNotIn(unsupported, body)
        self.assertIn("ai.stop_reason !== 'end_turn'", NODES["Check AI answer"]["parameters"]["jsCode"])

    def test_node_count_matches_readme(self):
        self.assertEqual(len(MAIN["nodes"]), 29)
        self.assertEqual(len(WEEKLY["nodes"]), 6)


if __name__ == "__main__":
    unittest.main()
