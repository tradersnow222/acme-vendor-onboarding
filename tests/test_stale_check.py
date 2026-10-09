import csv
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.approvals import record_decision
from scripts.samples import SAMPLES_DIR, load_sample
from scripts.status import audit_path, read_audit
from scripts.ticket import create_ticket, read_ticket, ticket_path
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent
ZENDESK = load_sample("zendesk")
NUDGE_AT = ZENDESK["expected"]["status"]["nudges"][0]["at"]
with open(SAMPLES_DIR / ZENDESK["expected"]["status"]["audit_file"], newline="") as f:
    CARDS_ROW = next(row for row in csv.DictReader(f) if row["step"] == "Approval cards sent")
REQUESTED_AT = datetime.fromisoformat(CARDS_ROW["timestamp_pt"]).isoformat()
NUDGE_LINE = f"VR-0001: security has waited 24.4 hours since {REQUESTED_AT}; nudge due\n"


class StaleCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name) / "tickets"
        self.runs = Path(self.tmp.name) / "runs"
        ticket = create_ticket("VR-0001", ZENDESK["expected"]["intake"]["fields"], self.tickets)
        reply = ZENDESK["approver_replies"][0]
        approvers = record_decision(ticket["approvers"], reply["role"], reply["approver"],
                                    reply["decision"], reply["time"], reply["conditions"])
        approvers["security"] = {"name": None, "decision": "waiting", "at": None, "conditions": [],
                                 "requested_at": REQUESTED_AT}
        ticket["route"] = ZENDESK["expected"]["routing"]["route"]
        ticket["approvers"] = approvers
        write_ticket(ticket, "VR-0001", self.tickets)
        self.ticket_file = ticket_path("VR-0001", self.tickets)
        self.ticket_bytes = self.ticket_file.read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.stale_check", *args,
             "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_not_stale_yet_prints_nothing(self):
        result = self.run_check("--now", "2026-10-09T05:00:00-07:00")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.ticket_file.read_bytes(), self.ticket_bytes)

    def test_stale_approval_is_listed_without_writing(self):
        result = self.run_check("--now", NUDGE_AT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, NUDGE_LINE)
        self.assertEqual(self.ticket_file.read_bytes(), self.ticket_bytes)
        self.assertFalse(audit_path("VR-0001", self.runs).exists())

    def test_record_logs_one_nudge_and_keeps_waiting(self):
        result = self.run_check("--now", NUDGE_AT, "--record")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, NUDGE_LINE)
        ticket = read_ticket("VR-0001", self.tickets)
        self.assertEqual(ticket["counts"]["nudges"], 1)
        self.assertEqual(ticket["counts"]["nudges"], ZENDESK["expected"]["status"]["logged_not_counted"]["nudges"])
        self.assertEqual(ticket["approvers"]["security"]["nudged_at"], NUDGE_AT)
        self.assertEqual(ticket["approvers"]["security"]["decision"], "waiting")
        self.assertEqual(read_audit("VR-0001", self.runs), [{
            "step_id": "1", "step": "Stale-approval nudge", "actor_type": "script",
            "actor": "scripts.stale_check", "timestamp_pt": NUDGE_AT, "what_they_saw": "",
            "outcome": "nudge due for security; silence is not a yes", "est_cost": "~0",
            "could_be_done_by": "", "data_label": "SYNTHESIZED",
        }])

        ticket_bytes = self.ticket_file.read_bytes()
        audit_bytes = audit_path("VR-0001", self.runs).read_bytes()
        again = self.run_check("--now", NUDGE_AT, "--record")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout, "")
        self.assertEqual(self.ticket_file.read_bytes(), ticket_bytes)
        self.assertEqual(audit_path("VR-0001", self.runs).read_bytes(), audit_bytes)

    def test_unrequested_and_closed_tickets_are_never_listed(self):
        for request_id, name in (("VR-0002", "figma"), ("VR-0003", "asana")):
            create_ticket(request_id, load_sample(name)["expected"]["intake"]["fields"], self.tickets)
        closed = read_ticket("VR-0003", self.tickets)
        closed["approvers"]["manager"]["requested_at"] = REQUESTED_AT
        closed["closed_at"] = NUDGE_AT
        write_ticket(closed, "VR-0003", self.tickets)
        result = self.run_check("--now", "2026-10-12T10:00:00-07:00")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"VR-0001: security has waited 96.4 hours since {REQUESTED_AT}; nudge due\n")

    def test_now_without_offset_is_a_usage_error(self):
        result = self.run_check("--now", "2026-10-09T10:00:00", "--record")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "--now needs a UTC offset: '2026-10-09T10:00:00'\n"
                                        "example: python3 -m scripts.stale_check --now 2026-10-09T10:00:00-07:00\n")
        self.assertEqual(self.ticket_file.read_bytes(), self.ticket_bytes)
        self.assertFalse(audit_path("VR-0001", self.runs).exists())


if __name__ == "__main__":
    unittest.main()
