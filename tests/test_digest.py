import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.approvals import record_decision
from scripts.samples import load_sample
from scripts.status import append_audit_row
from scripts.ticket import create_ticket, ticket_path
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = "2026-10-09T12:00:00-07:00"


def person_row(step, actor, timestamp):
    return {"step": step, "actor_type": "person", "actor": actor, "timestamp_pt": timestamp,
            "what_they_saw": "request", "outcome": "done", "est_cost": "~5 min",
            "could_be_done_by": "person", "data_label": "SYNTHESIZED"}


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets_dir = Path(self.tmp.name) / "tickets"
        self.runs_dir = Path(self.tmp.name) / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def make_ticket(self, name, reply_count, security=False, closed=False):
        sample = load_sample(name)
        request_id = sample["request_id"]
        ticket = create_ticket(request_id, sample["expected"]["intake"]["fields"], self.tickets_dir)
        if security:
            ticket["approvers"]["security"] = {"name": None, "decision": "waiting", "at": None, "conditions": []}
        append_audit_row(request_id, person_row("Request received", sample["people"]["requester"]["name"],
                                                sample["messages"][0]["time"]), self.runs_dir)
        for r in sample["approver_replies"][:reply_count]:
            ticket["approvers"] = record_decision(
                ticket["approvers"], r["role"], r["approver"], r["decision"], r["time"], r["conditions"]
            )
            append_audit_row(request_id, person_row(f"{r['role']} decision", r["approver"], r["time"]),
                             self.runs_dir)
        if closed:
            ticket["closed_at"] = sample["approver_replies"][-1]["time"]
            ticket["final_decision"] = "approved"
        write_ticket(ticket, request_id, self.tickets_dir)

    def make_all_samples(self):
        self.make_ticket("zendesk", 1, security=True)
        self.make_ticket("asana", 0)
        self.make_ticket("figma", 1, closed=True)

    def run_digest(self, now=NOW):
        return subprocess.run(
            [sys.executable, "-m", "scripts.digest", "--tickets-dir", str(self.tickets_dir),
             "--runs-dir", str(self.runs_dir), "--now", now],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_lists_open_requests_sums_steps_and_writes_nothing(self):
        self.make_all_samples()
        paths = [ticket_path(rid, self.tickets_dir) for rid in ("VR-0001", "VR-0002", "VR-0003")]
        before = [p.read_bytes() for p in paths]
        result = self.run_digest()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "Acme vendor digest 2026-10-09: 2 open request(s)",
            "VR-0001 Zendesk, Inc.: waiting, days open 1.1, exceptions 0, waiting on security",
            "VR-0003 Asana, Inc.: waiting, days open 0.0, exceptions 0, waiting on manager",
            "steps so far: 0 script, 0 model, 3 person",
        ])
        self.assertEqual([p.read_bytes() for p in paths], before)

    def test_quiet_when_nothing_is_open(self):
        self.make_ticket("figma", 1, closed=True)
        self.make_ticket("zendesk", 2, security=True, closed=True)
        (Path(self.tmp.name) / "empty").mkdir()
        for tickets_dir in [self.tickets_dir, Path(self.tmp.name) / "empty", Path(self.tmp.name) / "missing"]:
            with self.subTest(tickets_dir=tickets_dir.name):
                self.tickets_dir = tickets_dir
                result = self.run_digest()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_time_without_offset_is_refused(self):
        self.make_all_samples()
        result = self.run_digest(now="2026-10-09T12:00:00")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "--now has no UTC offset: 2026-10-09T12:00:00\n"
                                        "example: python3 -m scripts.digest --now 2026-10-09T12:00:00-07:00\n")


if __name__ == "__main__":
    unittest.main()
