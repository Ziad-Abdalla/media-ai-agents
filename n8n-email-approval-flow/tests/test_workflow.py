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
NODES = {n["name"]: n for n in MAIN["nodes"]}


class WorkflowRules(unittest.TestCase):
    def test_failures_go_to_the_error_workflow(self):
        self.assertEqual(MAIN["settings"]["errorWorkflow"], ERRORS["id"])

    def test_every_credential_is_in_the_template(self):
        template_ids = {c["id"] for c in load("credentials/credentials.template.json")}
        for wf in (MAIN, ERRORS):
            for node in wf["nodes"]:
                for cred in node.get("credentials", {}).values():
                    self.assertIn(cred["id"], template_ids, node["name"])

    def test_sql_values_are_passed_as_one_list(self):
        # The comma bug: the comma-separated box splits "crane (jib, 30 ft)" in two.
        for wf in (MAIN, ERRORS):
            for node in wf["nodes"]:
                if node["type"] == "n8n-nodes-base.postgres":
                    values = node["parameters"]["options"]["queryReplacement"]
                    self.assertTrue(values.startswith("={{ ["), node["name"])

    def test_webhook_needs_a_login(self):
        self.assertEqual(NODES["New email arrived"]["parameters"]["authentication"], "basicAuth")

    def test_approve_needs_the_approve_token(self):
        email = NODES["Ask manager to approve"]["parameters"]["text"]
        self.assertIn("decision=approve&t={{ $json.approve_token }}", email)
        self.assertIn("decision=reject&t={{ $json.reject_token }}", email)
        check = NODES["Approved?"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
        self.assertIn("approve_token", check)

    def test_duplicate_guard_still_outputs_on_conflict(self):
        # Without this, a duplicate returns zero items and "First time we see it?" never runs.
        self.assertTrue(NODES["Claim Message-ID"].get("alwaysOutputData"))

    def test_only_one_path_into_bookings(self):
        writers = [n["name"] for n in MAIN["nodes"] if "INSERT INTO bookings" in n["parameters"].get("query", "")]
        self.assertEqual(writers, ["Save booking"])
        into_save = [src for src, out in MAIN["connections"].items()
                     for branch in out["main"] for link in branch if link["node"] == "Save booking"]
        self.assertEqual(into_save, ["Approved?"])

    def test_node_count_matches_readme(self):
        self.assertEqual(len(MAIN["nodes"]), 21)


if __name__ == "__main__":
    unittest.main()
