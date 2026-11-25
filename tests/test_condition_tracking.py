import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.approvals import record_decision
from scripts.samples import load_sample
from scripts.ticket import create_ticket, read_ticket, ticket_path
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent


class ConditionTrackingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name) / "tickets"
        self.runs = Path(self.tmp.name) / "runs"
        self.sample = load_sample("zendesk")
        self.request_id = self.sample["request_id"]
        self.conditions = self.sample["approver_replies"][1]["conditions"]
        self.start = self.sample["expected"]["intake"]["fields"]["target_start_date"]["value"]
        ticket = create_ticket(self.request_id, self.sample["expected"]["intake"]["fields"], self.tickets)
        ticket["created_at"] = self.sample["messages"][0]["time"]
        ticket["approvers"]["security"] = {"name": None, "decision": "waiting", "at": None, "conditions": []}
        for reply in self.sample["approver_replies"]:
            ticket["approvers"] = record_decision(
                ticket["approvers"], reply["role"], reply["approver"], reply["decision"],
                reply["time"], reply["conditions"],
            )
        write_ticket(ticket, self.request_id, self.tickets)

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, day):
        return f"{day.isoformat()}T09:00:00-07:00"

    def run_script(self, module, *args):
        return subprocess.run(
            [sys.executable, "-m", module, *args, "--tickets-dir", str(self.tickets)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def warning(self, pending):
        return (f"start date {self.start} is within 3 days or past; "
                f"pending conditions: {'; '.join(pending)}")

    def test_pending_conditions_are_flagged_near_the_start_date(self):
        start = date.fromisoformat(self.start)
        outside = self.at(start - timedelta(days=4))
        within = self.at(start - timedelta(days=3))
        past = self.at(start + timedelta(days=1))
        done = self.conditions[0]
        still_pending = self.conditions[1:]

        early_status = self.run_script("scripts.status", "--ticket", self.request_id, "--runs-dir", str(self.runs), "--now", outside)
        early_stale = self.run_script("scripts.stale_check", "--runs-dir", str(self.runs), "--now", outside)
        self.assertEqual(early_status.returncode, 0, early_status.stderr)
        self.assertEqual(early_stale.returncode, 0, early_stale.stderr)
        self.assertNotIn("warning:", early_status.stdout)
        self.assertEqual(early_stale.stdout, "")
        self.assertIn(f"{done} (pending)", early_status.stdout)

        before = ticket_path(self.request_id, self.tickets).read_bytes()
        near_status = self.run_script("scripts.status", "--ticket", self.request_id, "--runs-dir", str(self.runs), "--now", within)
        near_stale = self.run_script("scripts.stale_check", "--runs-dir", str(self.runs), "--now", within)
        self.assertEqual(near_status.returncode, 0, near_status.stderr)
        self.assertIn(f"warning: {self.warning(self.conditions)}", near_status.stdout)
        self.assertEqual(near_stale.stdout, f"{self.request_id}: {self.warning(self.conditions)}\n")
        self.assertEqual(ticket_path(self.request_id, self.tickets).read_bytes(), before)

        marked = self.run_script(
            "scripts.mark_condition", "--ticket", self.request_id, "--role", "security",
            "--condition", done, "--status", "complete",
        )
        self.assertEqual(marked.returncode, 0, marked.stderr)
        self.assertEqual(marked.stdout, f"{self.request_id}: security condition marked complete: {done}\n")
        self.assertEqual(read_ticket(self.request_id, self.tickets)["approvers"]["security"]["condition_status"][done],
                         "complete")
        self.assertNotEqual(ticket_path(self.request_id, self.tickets).read_bytes(), before)

        past_status = self.run_script("scripts.status", "--ticket", self.request_id, "--runs-dir", str(self.runs), "--now", past)
        past_stale = self.run_script("scripts.stale_check", "--runs-dir", str(self.runs), "--now", past)
        self.assertIn(f"{done} (complete)", past_status.stdout)
        self.assertIn(f"warning: {self.warning(still_pending)}", past_status.stdout)
        self.assertEqual(past_stale.stdout, f"{self.request_id}: {self.warning(still_pending)}\n")

        for text in still_pending:
            waived = self.run_script(
                "scripts.mark_condition", "--ticket", self.request_id, "--role", "security",
                "--condition", text, "--status", "waived",
            )
            self.assertEqual(waived.returncode, 0, waived.stderr)
        clear_status = self.run_script("scripts.status", "--ticket", self.request_id, "--runs-dir", str(self.runs), "--now", past)
        clear_stale = self.run_script("scripts.stale_check", "--runs-dir", str(self.runs), "--now", past)
        self.assertNotIn("warning:", clear_status.stdout)
        self.assertEqual(clear_stale.stdout, "")
        for text in still_pending:
            self.assertIn(f"{text} (waived)", clear_status.stdout)

        missing = self.run_script(
            "scripts.mark_condition", "--ticket", self.request_id, "--role", "security",
            "--condition", "not a real condition", "--status", "complete",
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("no condition", missing.stderr)
