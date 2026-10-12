"""Run the workflow's own SQL against a real Postgres: the clash check, Save booking and the KPI view.

    python -m unittest discover tests

Optional: these run only when the Postgres container from docker-compose is up (`docker compose up -d`),
and are skipped otherwise. They create a throwaway database `bookings_test`, load db/init.sql into it,
and drop it at the end; the demo database is never touched.

The SQL is read straight from the workflow JSON and run as a prepared statement with $1, $2...
parameters, the same way n8n's Postgres node sends it. Each test runs inside BEGIN ... ROLLBACK.
"""
import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN = json.loads((ROOT / "workflows/booking-requests.json").read_text(encoding="utf8"))
QUERY = {n["name"]: n["parameters"]["query"].strip().rstrip(";")
         for n in MAIN["nodes"] if n["type"] == "n8n-nodes-base.postgres"}
TEST_DB = "bookings_test"


def psql(script, db=TEST_DB):
    """Run a SQL script in the container; return the printed rows as lists of strings."""
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "bookings", "-d", db,
         "-q", "-At", "-F", "|", "-v", "ON_ERROR_STOP=1"],
        input=script, cwd=ROOT, capture_output=True, text=True, encoding="utf8")
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return [line.split("|") for line in out.stdout.splitlines() if line]


def postgres_is_up():
    try:
        psql("SELECT 1;", db="bookings_app")
        return True
    except (OSError, AssertionError):
        return False


def email(message_id, resource="CAM-ALEXA-LF", qty=1, start="2026-10-21", end="2026-10-23",
          status="received", route="ready", production="Test Show", received="now()", decided="NULL"):
    """An email_log row (synthetic). `received` / `decided` are SQL expressions."""
    return (f"INSERT INTO email_log (message_id, status, route, resource_code, quantity, start_date, end_date, "
            f"production, received_at, decided_at) VALUES ('{message_id}', '{status}', '{route}', "
            f"NULLIF('{resource}', ''), {qty}, '{start}', '{end}', '{production}', {received}, {decided});\n")


def booking(message_id, resource="CAM-ALEXA-LF", qty=2, start="2026-10-20", end="2026-10-22", cancelled=False):
    row = email(message_id, resource, qty, start, end, status="approved", production="Desert Rose")
    return row + (f"INSERT INTO bookings (message_id, request_type, resource_code, item, quantity, start_date, "
                  f"end_date, production, requester_email, cancelled_at) VALUES ('{message_id}', 'equipment', "
                  f"'{resource}', 'kit', {qty}, '{start}', '{end}', 'Desert Rose', 'a@sadafprod.test', "
                  f"{'now()' if cancelled else 'NULL'});\n")


@unittest.skipUnless(postgres_is_up(), "needs the Postgres container (docker compose up -d)")
class WorkflowSQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        psql(f"DROP DATABASE IF EXISTS {TEST_DB};\nCREATE DATABASE {TEST_DB};", db="bookings_app")
        psql((ROOT / "db/init.sql").read_text(encoding="utf8"))

    @classmethod
    def tearDownClass(cls):
        psql(f"DROP DATABASE IF EXISTS {TEST_DB};", db="bookings_app")

    def in_transaction(self, setup, last):
        return psql(f"BEGIN;\n{setup}\n{last}\nROLLBACK;")

    def clash(self, setup, qty=1, resource="CAM-ALEXA-LF"):
        """Run 'Check for clashes' for a new request m-new (21 to 23 Oct). Returns (taken, is_clash) or None."""
        rows = self.in_transaction(
            setup + email("m-new", resource, qty) + f"PREPARE clash AS {QUERY['Check for clashes']};",
            f"EXECUTE clash('m-new', '{resource}', '2026-10-21', '2026-10-23', {qty});\n"
            "SELECT 'flag', clash FROM email_log WHERE message_id = 'm-new';")
        result = [r for r in rows if r[0] != "flag"]
        flag = [r for r in rows if r[0] == "flag"][0][1]
        if not result:
            return None
        code, units, taken, is_clash, overlapping = result[0]
        self.assertEqual(flag, is_clash)   # the same statement stores the flag on the email
        return int(taken), is_clash == "t"

    def test_booked_and_waiting_on_overlapping_dates_are_added_up(self):
        # 3 kits owned. Desert Rose has 2 booked on 20-22 Oct; a request for 1 more still fits.
        self.assertEqual(self.clash(booking("m-booked")), (2, False))
        # Asking for 2 does not fit.
        self.assertEqual(self.clash(booking("m-booked"), qty=2), (2, True))
        # A request still waiting for the manager counts too.
        self.assertEqual(self.clash(booking("m-booked") + email("m-wait", start="2026-10-23", end="2026-10-23")),
                         (3, True))

    def test_dates_that_do_not_overlap_are_not_counted(self):
        self.assertEqual(self.clash(booking("m-booked", start="2026-10-24", end="2026-10-25"), qty=3), (0, False))
        # Ranges include both ends: a booking ending on the 21st overlaps a request starting on the 21st.
        self.assertEqual(self.clash(booking("m-booked", start="2026-10-19", end="2026-10-21"), qty=2), (2, True))

    def test_cancelled_bookings_and_closed_requests_are_not_counted(self):
        self.assertEqual(self.clash(booking("m-booked", cancelled=True), qty=2), (0, False))
        self.assertEqual(self.clash(email("m-old", status="rejected"), qty=3), (0, False))

    def test_item_outside_the_catalogue_is_not_checked(self):
        self.assertIsNone(self.clash("", resource=""))

    def save_booking(self, setup, resource):
        params = ("'m-new', 'equipment', '{r}', 'kit', 1, '2026-10-21', '2026-10-23', 'Test Show', "
                  "'Sara', 'sara@sadafprod.test', 'en', ''").format(r=resource)
        return self.in_transaction(
            setup + email("m-new", resource) + f"PREPARE save AS {QUERY['Save booking']};",
            f"EXECUTE save({params});\nEXECUTE save({params});\n"
            "SELECT 'row', odoo_sync FROM bookings WHERE message_id = 'm-new';\n"
            "SELECT 'status', status, decided_at IS NOT NULL FROM email_log WHERE message_id = 'm-new';")

    def test_save_booking_books_once_and_marks_the_email_approved(self):
        rows = self.save_booking("", "CAM-ALEXA-LF")
        returned = [r for r in rows if r[0] not in ("row", "status")]
        self.assertEqual(len(returned), 1)   # the second EXECUTE inserts nothing and returns nothing
        self.assertIn(["row", "not_sent"], rows)
        self.assertIn(["status", "approved", "t"], rows)

    def test_odoo_switch_on_with_no_odoo_record_is_marked_skipped(self):
        on = "UPDATE app_settings SET value = 'on' WHERE key = 'odoo_sync';\n"
        self.assertIn(["row", "skipped_no_target"], self.save_booking(on, ""))
        linked = on + "UPDATE resources SET odoo_res_model_id = 1, odoo_res_id = 1 WHERE code = 'CAM-ALEXA-LF';\n"
        self.assertIn(["row", "not_sent"], self.save_booking(linked, "CAM-ALEXA-LF"))

    def test_kpi_view(self):
        setup = (
            email("e1", status="approved", decided="now()")
            + email("e2", status="rejected", decided="now()")
            + email("e3", status="invalid_click", decided="now()")
            + email("e4", status="needs_info", route="needs_info")
            + email("e5", status="ignored", route="not_booking", resource="")
            # Received 10 days ago, decided today: counts as a decision this week, not as a request.
            + email("e6", status="approved", received="now() - interval '10 days'", decided="now()")
        )
        rows = self.in_transaction(setup, "SELECT booking_requests, auto_routed, approved, rejected, expired, "
                                          "invalid_clicks, approval_rate_pct, est_minutes_saved FROM kpi_last_7_days;")
        requests, auto, approved, rejected, expired, invalid, rate, saved = rows[0]
        self.assertEqual((requests, auto), ("4", "3"))
        self.assertEqual((approved, rejected, expired, invalid), ("2", "1", "0", "1"))
        self.assertEqual(rate, "66.7")    # 2 of 3 decisions; the invalid click is not a decision
        self.assertEqual(saved, "18")     # 3 complete requests x 6 minutes; needs_info saves nothing


if __name__ == "__main__":
    unittest.main()
