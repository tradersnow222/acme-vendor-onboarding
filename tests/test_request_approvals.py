import csv
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.samples import SAMPLES_DIR, load_sample
from scripts.status import audit_path, read_audit
from scripts.ticket import create_ticket, read_ticket, ticket_path
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent


def zendesk_audit_time(step):
    with open(SAMPLES_DIR / "vr-0001-zendesk-audit.csv", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["step"] == step)
    return datetime.fromisoformat(row["timestamp_pt"]).isoformat()


CARDS_SENT_AT = zendesk_audit_time("Approval cards sent")
NUDGE_AT = zendesk_audit_time("Stale-approval check")


class RequestApprovalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name) / "tickets"
        self.runs = Path(self.tmp.name) / "runs"
        self.sample = load_sample("zendesk")
        create_ticket("VR-0001", self.sample["expected"]["intake"]["fields"], self.tickets)
        self.ticket_file = ticket_path("VR-0001", self.tickets)

    def tearDown(self):
        self.tmp.cleanup()

    def run_request(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.request_approvals", *args,
             "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def mark_research_done(self, request_id):
        ticket = read_ticket(request_id, self.tickets)
        ticket["research"]["status"] = "done"
        write_ticket(ticket, request_id, self.tickets)

    def request_zendesk(self):
        self.mark_research_done("VR-0001")
        return self.run_request("--ticket", "VR-0001", "--at", CARDS_SENT_AT, "--today", "2026-10-08")

    def test_blocked_until_pack_check_passes(self):
        before = self.ticket_file.read_bytes()
        result = self.run_request("--ticket", "VR-0001", "--at", CARDS_SENT_AT, "--today", "2026-10-08")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "VR-0001: blocked: pack check has not passed\n")
        self.assertEqual(self.ticket_file.read_bytes(), before)
        self.assertFalse(audit_path("VR-0001", self.runs).exists())

    def test_requests_each_routed_approver(self):
        result = self.request_zendesk()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         "VR-0001: approval requested from manager, security at 2026-10-08T09:36:00-07:00\n")
        ticket = read_ticket("VR-0001", self.tickets)
        self.assertEqual(ticket["route"], ["manager", "security"])
        self.assertEqual(ticket["route"], self.sample["expected"]["routing"]["route"])
        waiting = {"name": None, "decision": "waiting", "at": None, "conditions": [],
                   "requested_at": "2026-10-08T09:36:00-07:00"}
        self.assertEqual(ticket["approvers"], {"manager": waiting, "security": waiting})
        rows = read_audit("VR-0001", self.runs)
        self.assertEqual([(r["step"], r["outcome"]) for r in rows],
                         [("Approval requested", "manager asked"), ("Approval requested", "security asked")])

    def test_second_run_keeps_original_times(self):
        self.request_zendesk()
        ticket_before = self.ticket_file.read_bytes()
        audit_before = audit_path("VR-0001", self.runs).read_bytes()
        result = self.run_request("--ticket", "VR-0001", "--at", NUDGE_AT, "--today", "2026-10-09")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "VR-0001: approvals already requested: "
                         "manager 2026-10-08T09:36:00-07:00, security 2026-10-08T09:36:00-07:00\n")
        self.assertEqual(self.ticket_file.read_bytes(), ticket_before)
        self.assertEqual(audit_path("VR-0001", self.runs).read_bytes(), audit_before)

    def test_figma_routes_to_manager_only(self):
        figma = load_sample("figma")
        create_ticket("VR-0002", figma["expected"]["intake"]["fields"], self.tickets)
        self.mark_research_done("VR-0002")
        result = self.run_request("--ticket", "VR-0002", "--at", figma["messages"][0]["time"],
                                  "--today", "2026-10-09")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "VR-0002: approval requested from manager at 2026-10-09T10:05:00-07:00\n")
        ticket = read_ticket("VR-0002", self.tickets)
        self.assertEqual(ticket["route"], ["manager"])
        self.assertEqual(ticket["route"], figma["expected"]["routing"]["route"])

    def test_time_without_offset_exits_2(self):
        self.mark_research_done("VR-0001")
        before = self.ticket_file.read_bytes()
        result = self.run_request("--ticket", "VR-0001", "--at", "2026-10-08T09:36:00")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.splitlines()[1],
                         "example: python3 -m scripts.request_approvals --ticket VR-0001 --at 2026-10-08T09:36:00-07:00")
        self.assertEqual(self.ticket_file.read_bytes(), before)
        self.assertFalse(audit_path("VR-0001", self.runs).exists())


if __name__ == "__main__":
    unittest.main()
