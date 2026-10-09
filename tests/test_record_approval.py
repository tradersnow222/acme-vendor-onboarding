import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.samples import load_sample
from scripts.status import append_audit_row, audit_path, build_status, read_audit
from scripts.ticket import create_ticket, read_ticket, ticket_path
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUESTED_AT = "2026-10-08T09:36:00-07:00"


class RecordApprovalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets_dir = Path(self.tmp.name) / "tickets"
        self.runs_dir = Path(self.tmp.name) / "runs"
        self.sample = load_sample("zendesk")
        ticket = create_ticket("VR-0001", self.sample["expected"]["intake"]["fields"], self.tickets_dir)
        ticket["created_at"] = self.sample["messages"][0]["time"]
        ticket["approvers"]["security"] = {"name": None, "decision": "waiting", "at": None, "conditions": [],
                                           "requested_at": REQUESTED_AT}
        write_ticket(ticket, "VR-0001", self.tickets_dir)
        append_audit_row("VR-0001", {
            "step": "Request received", "actor_type": "person",
            "actor": self.sample["people"]["requester"]["name"], "timestamp_pt": self.sample["messages"][0]["time"],
            "what_they_saw": "n/a", "outcome": "request", "est_cost": "~0", "data_label": "SYNTHESIZED",
        }, self.runs_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, reply, **overrides):
        args = {"--role": reply["role"], "--name": reply["approver"], "--decision": reply["decision"],
                "--quote": reply["note"] or "approved", "--at": reply["time"], **overrides}
        argv = [sys.executable, "-m", "scripts.record_approval", "--ticket", "VR-0001",
                "--tickets-dir", str(self.tickets_dir), "--runs-dir", str(self.runs_dir)]
        for flag, value in args.items():
            argv += [flag, value]
        for condition in reply["conditions"]:
            argv += ["--condition", condition]
        return subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True)

    def test_replays_zendesk_replies_to_expected_status(self):
        manager, security = self.sample["approver_replies"]
        first = self.record(manager)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, "VR-0001: recorded manager Daniel Okafor [SYNTHESIZED] approved; overall waiting\n")
        second = self.record(security)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, "VR-0001: recorded security Lena Hoffmann [SYNTHESIZED] "
                                        "approved_with_conditions; overall approved_with_conditions\n")

        ticket = read_ticket("VR-0001", self.tickets_dir)
        rows = read_audit("VR-0001", self.runs_dir)
        expected = self.sample["expected"]["status"]
        status = build_status({**ticket, "closed_at": expected["decided_at"]}, rows, "2026-10-10T00:00:00-07:00")
        self.assertEqual(status["decision"], expected["decision"])
        self.assertEqual(status["decision"], "approved_with_conditions")
        self.assertEqual(status["days_open"], expected["days_open"])
        self.assertEqual(status["days_open"], 1.1)
        self.assertEqual(ticket["approvers"]["security"]["conditions"], security["conditions"])
        self.assertEqual(ticket["approvers"]["security"]["requested_at"], REQUESTED_AT)
        self.assertEqual([r["step"] for r in rows], ["Request received", "Approval", "Approval"])
        self.assertEqual(rows[1]["actor"], "Daniel Okafor [SYNTHESIZED]")
        self.assertEqual(rows[1]["outcome"], 'approved: "Fine for 90 days on Suite Professional monthly, cap 8 seats."')
        self.assertEqual(rows[2]["outcome"], 'approved_with_conditions: "approved"; conditions: '
                                             + "; ".join(security["conditions"]))

    def test_refusals_leave_ticket_and_audit_unchanged(self):
        manager, security = self.sample["approver_replies"]
        self.assertEqual(self.record(manager).returncode, 0)
        ticket_bytes = ticket_path("VR-0001", self.tickets_dir).read_bytes()
        audit_bytes = audit_path("VR-0001", self.runs_dir).read_bytes()
        cases = {
            "bot name": (security, {"--name": "Acme bot"}, "not a named person: 'Acme bot'"),
            "role not in route": (security, {"--role": "legal"}, "role 'legal' is not in the route"),
            "second manager decision": (manager, {}, "cannot move manager from approved to approved"),
        }
        for name, (reply, overrides, message) in cases.items():
            with self.subTest(case=name):
                result = self.record(reply, **overrides)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, f"VR-0001: not recorded: {message}\n")
                self.assertEqual(ticket_path("VR-0001", self.tickets_dir).read_bytes(), ticket_bytes)
                self.assertEqual(audit_path("VR-0001", self.runs_dir).read_bytes(), audit_bytes)


if __name__ == "__main__":
    unittest.main()
