"""Run the workflow's Code nodes for real, with fake inputs. Needs Node.js; no Docker, no API calls.

    python -m unittest discover tests

The JavaScript is read straight from the exported workflow JSON, so these test exactly what n8n runs.
Each test feeds one node a made-up Claude answer or clash result and checks what comes out.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "run_code_node.js"
MAIN = json.loads((ROOT / "workflows/booking-requests.json").read_text(encoding="utf8"))
WEEKLY = json.loads((ROOT / "workflows/weekly-summary.json").read_text(encoding="utf8"))
CODE = {n["name"]: n["parameters"]["jsCode"] for wf in (MAIN, WEEKLY) for n in wf["nodes"]
        if n["type"] == "n8n-nodes-base.code"}

CATALOGUE = [
    {"code": "CAM-ALEXA-LF", "kind": "equipment", "name_en": "ARRI Alexa Mini LF camera kit",
     "name_ar": "طقم كاميرا ARRI Alexa Mini LF", "units": 3},
    {"code": "STUDIO-2", "kind": "studio", "name_en": "Studio 2 (green screen)",
     "name_ar": "استوديو 2 (شاشة خضراء)", "units": 1},
]
EMAIL_EN = {"MessageID": "m1@sadafprod.test", "Subject": "Camera kit for Desert Rose",
            "Text": "Please book 2 ARRI kits for Desert Rose from 20 to 22 October 2026.",
            "From": {"Name": "Layla Hassan", "Address": "Layla.Hassan@sadafprod.test"}}
EMAIL_AR = {"MessageID": "m2@sadafprod.test", "Subject": "حجز كاميرات",
            "Text": "نحتاج طقمين من كاميرات ARRI لمسلسل ليالي الرياض من 21 إلى 23 أكتوبر 2026",
            "From": {"Name": "Khalid Al-Harbi", "Address": "khalid.harbi@sadafprod.test"}}


def claude_reply(stop_reason="end_turn", **fields):
    answer = {"is_booking_request": True, "request_type": "equipment", "item": "2 ARRI Alexa Mini LF kits",
              "resource_code": "CAM-ALEXA-LF", "quantity": 2, "start_date": "2026-10-20",
              "end_date": "2026-10-22", "production": "Desert Rose", "production_as_written": "Desert Rose",
              "requester_name": "Layla Hassan", "notes": "", "confidence": 0.9}
    answer.update(fields)
    return {"stop_reason": stop_reason, "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": json.dumps(answer)}],
            "usage": {"input_tokens": 1000, "output_tokens": 200}}


def run(node, input_json, nodes=None):
    payload = {"code": CODE[node], "input": input_json, "nodes": nodes or {},
               "resumeUrl": "http://localhost:5678/webhook-waiting/7?signature=abc"}
    out = subprocess.run(["node", str(HARNESS)], input=json.dumps(payload), capture_output=True,
                         text=True, encoding="utf8", check=True)
    return json.loads(out.stdout)


def check(reply, email=EMAIL_EN):
    out = run("Check AI answer", reply, {"Fetch full email": email, "Load catalogue": {"catalogue": CATALOGUE}})
    return out["items"][0] if out["ok"] else out


@unittest.skipUnless(shutil.which("node"), "needs Node.js")
class CheckAIAnswer(unittest.TestCase):
    def test_complete_request_is_ready_with_catalogue_item(self):
        r = check(claude_reply())
        self.assertEqual(r["route"], "ready")
        self.assertEqual(r["resource_code"], "CAM-ALEXA-LF")
        self.assertEqual(r["resource_units"], 3)
        self.assertEqual(r["from_address"], "layla.hassan@sadafprod.test")
        self.assertAlmostEqual(r["cost_usd"], 1000 * 0.10 / 1e6 + 200 * 0.50 / 1e6)
        self.assertNotEqual(r["approve_token"], r["reject_token"])

    def test_claude_stopping_early_fails_loudly(self):
        out = check(claude_reply(stop_reason="max_tokens"))
        self.assertFalse(out["ok"])
        self.assertIn("stopped early", out["error"])

    def test_impossible_date_goes_to_needs_info(self):
        r = check(claude_reply(start_date="2026-02-30", end_date="2026-02-30"))
        self.assertEqual(r["route"], "needs_info")
        self.assertIn("the date you need it", r["missing"])

    def test_end_before_start_goes_to_needs_info(self):
        r = check(claude_reply(start_date="2026-10-22", end_date="2026-10-20"))
        self.assertEqual(r["route"], "needs_info")

    def test_low_confidence_goes_to_needs_info(self):
        self.assertEqual(check(claude_reply(confidence=0.5))["route"], "needs_info")

    def test_code_not_in_catalogue_is_dropped(self):
        r = check(claude_reply(resource_code="MADE-UP"))
        self.assertEqual(r["resource_code"], "")

    def test_bad_quantity_becomes_one(self):
        self.assertEqual(check(claude_reply(quantity=0))["quantity"], 1)

    def test_language_comes_from_the_email_not_the_ai(self):
        self.assertEqual(check(claude_reply(), EMAIL_EN)["language"], "en")
        self.assertEqual(check(claude_reply(), EMAIL_AR)["language"], "ar")

    def test_needs_info_reply_is_in_the_requesters_language(self):
        r = check(claude_reply(start_date="", end_date=""), EMAIL_AR)
        self.assertEqual(r["route"], "needs_info")
        self.assertIn("التاريخ الذي تحتاجه فيه", r["reply_draft"])
        r = check(claude_reply(start_date="", end_date=""), EMAIL_EN)
        self.assertIn("could you tell us the date you need it?", r["reply_draft"])


def approval_email(clash, email=EMAIL_EN, **fields):
    r = check(claude_reply(**fields), email)
    return run("Write approval email", clash, {"Check AI answer": r})["items"][0], r


@unittest.skipUnless(shutil.which("node"), "needs Node.js")
class ApprovalEmail(unittest.TestCase):
    def test_links_carry_their_own_tokens(self):
        mail, r = approval_email({})
        self.assertIn(f"APPROVE: http://localhost:5678/webhook-waiting/7?signature=abc&decision=approve&t={r['approve_token']}", mail["text"])
        self.assertIn(f"REJECT:  http://localhost:5678/webhook-waiting/7?signature=abc&decision=reject&t={r['reject_token']}", mail["text"])

    def test_arabic_request_gets_a_right_to_left_arabic_email(self):
        mail, _ = approval_email({}, EMAIL_AR)
        self.assertIn('dir="rtl"', mail["html"])
        self.assertIn("موافقة", mail["html"])
        self.assertIn("طلب حجز", mail["subject"])

    def test_english_request_gets_a_left_to_right_email(self):
        mail, _ = approval_email({})
        self.assertIn('dir="ltr"', mail["html"])
        self.assertTrue(mail["subject"].startswith("Approve booking?"))

    def test_clash_is_shown_and_flagged_in_the_subject(self):
        clash = {"code": "CAM-ALEXA-LF", "units": 3, "already_taken": 2, "is_clash": True,
                 "overlapping": [{"state": "booked", "production": "Desert Rose", "start_date": "2026-10-20",
                               "end_date": "2026-10-22", "quantity": 2}]}
        mail, _ = approval_email(clash, EMAIL_AR)
        self.assertTrue(mail["is_clash"])
        self.assertTrue(mail["subject"].startswith("⚠"))
        self.assertIn("Desert Rose", mail["html"])
        self.assertIn("يوجد تعارض محتمل", mail["text"])

    def test_no_clash_and_not_in_catalogue_say_so(self):
        free = {"code": "CAM-ALEXA-LF", "units": 3, "already_taken": 0, "is_clash": False, "overlapping": []}
        self.assertIn("No clash: 0 of 3", approval_email(free)[0]["text"])
        self.assertIn("not in the catalogue", approval_email({})[0]["text"])

    def test_email_text_cannot_inject_html_into_the_managers_email(self):
        evil = dict(EMAIL_EN, Text='Book it <a href="http://evil.example">APPROVE HERE</a>')
        mail, _ = approval_email({}, evil, item='<img src=x onerror=alert(1)>')
        self.assertNotIn('<a href="http://evil.example">', mail["html"])
        self.assertNotIn("<img src=x", mail["html"])
        self.assertIn("&lt;img src=x", mail["html"])


@unittest.skipUnless(shutil.which("node"), "needs Node.js")
class ConfirmationAndWeekly(unittest.TestCase):
    def test_confirmation_language_follows_the_request(self):
        r = check(claude_reply(production_as_written="ليالي الرياض"), EMAIL_AR)
        mail = run("Write confirmation", {}, {"Check AI answer": r, "Save booking": {"booking_id": 4}})["items"][0]
        self.assertIn('dir="rtl"', mail["html"])
        self.assertIn("تأكيد الحجز رقم 4", mail["subject"])
        self.assertIn("ليالي الرياض", mail["text"])
        r = check(claude_reply())
        mail = run("Write confirmation", {}, {"Check AI answer": r, "Save booking": {"booking_id": 5}})["items"][0]
        self.assertEqual(mail["subject"], "Booking 5 confirmed: ARRI Alexa Mini LF camera kit")

    def test_weekly_summary_is_arabic_and_shows_the_kpis(self):
        kpis = {"emails_handled": "10", "booking_requests": "8", "auto_routed": "6", "needs_info": "2",
                "approved": "4", "rejected": "1", "expired_or_invalid": "0", "waiting_for_manager": "1",
                "clashes_flagged": "1", "auto_routed_pct": "75.0", "approval_rate_pct": "80.0",
                "avg_minutes_to_decision": "42.5", "median_minutes_to_decision": "30.0", "ai_calls": "9",
                "ai_cost_usd": "0.002100", "ai_cost_per_booking_usd": "0.000525", "est_minutes_saved": "48",
                "minutes_per_request": 6, "errors": "0",
                "upcoming": [{"resource": "استوديو 2", "production": "<b>Al Bait</b>", "start_date": "2026-11-02",
                              "end_date": "2026-11-04", "quantity": 1}]}
        out = run("Write Arabic summary", kpis)["items"][0]
        self.assertIn('dir="rtl"', out["html"])
        for shown in ("75.0%", "80.0%", "42.5 دقيقة", "$0.0021"):
            self.assertIn(shown, out["html"])
        self.assertIn("&lt;b&gt;Al Bait", out["html"])
        self.assertNotIn("upcoming", out["kpis"])


if __name__ == "__main__":
    unittest.main()
