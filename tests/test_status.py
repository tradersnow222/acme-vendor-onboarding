import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.approvals import record_decision
from scripts.samples import SAMPLES_DIR, load_sample
from scripts.status import append_audit_row, audit_path, build_status, read_audit
from scripts.ticket import create_ticket, read_ticket, ticket_path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = "2026-10-09T10:00:00-07:00"
ZENDESK_COUNTS = {
    "exceptions": {"missing_intake_fields": 1, "not_found_pack_rows": 2, "rejections": 0},
    "hedged_answers": 1,
    "nudges": 1,
}
LIVE_CREATED_AT = "2026-10-08T21:13:00-07:00"
LIVE_DECIDED_AT = "2026-10-09T11:24:00-07:00"


def person_row(step, actor, timestamp):
    return {"step": step, "actor_type": "person", "actor": actor, "timestamp_pt": timestamp,
            "what_they_saw": "request", "outcome": "done", "est_cost": "~5 min",
            "could_be_done_by": "person", "data_label": "SYNTHESIZED"}


LIVE_AUDIT_ROWS = [
    person_row("Approval requested", "Daniel Okafor [SYNTHESIZED]", "2026-10-09T09:00:00-07:00"),
    person_row("Manager decision", "Daniel Okafor [SYNTHESIZED]", LIVE_DECIDED_AT),
]


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets_dir = Path(self.tmp.name) / "tickets"
        self.runs_dir = Path(self.tmp.name) / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def make_ticket(self, sample, replies, security=False, counts=None, closed=False):
        ticket = create_ticket(sample["request_id"], sample["expected"]["intake"]["fields"], self.tickets_dir)
        ticket["created_at"] = sample["messages"][0]["time"]
        if closed:
            ticket["closed_at"] = sample["expected"]["status"]["decided_at"]
        if security:
            ticket["approvers"]["security"] = {"name": None, "decision": "waiting", "at": None, "conditions": []}
        for r in replies:
            ticket["approvers"] = record_decision(
                ticket["approvers"], r["role"], r["approver"], r["decision"], r["time"], r["conditions"]
            )
        ticket["counts"].update(counts or {})
        ticket_path(sample["request_id"], self.tickets_dir).write_text(json.dumps(ticket, indent=2) + "\n")

    def make_zendesk(self, reply_count=None):
        sample = load_sample("zendesk")
        self.make_ticket(sample, sample["approver_replies"][:reply_count], security=True, counts=ZENDESK_COUNTS,
                         closed=reply_count is None)
        audit_path("VR-0001", self.runs_dir).parent.mkdir(parents=True)
        shutil.copy(SAMPLES_DIR / "vr-0001-zendesk-audit.csv", audit_path("VR-0001", self.runs_dir))
        return sample["expected"]["status"]

    def status_of(self, request_id, now=NOW):
        return build_status(read_ticket(request_id, self.tickets_dir), read_audit(request_id, self.runs_dir), now)

    def test_zendesk_matches_expected_status(self):
        expected = self.make_zendesk()
        status = self.status_of("VR-0001")
        for key in ("decision", "days_open", "exceptions", "steps_by_actor_type"):
            self.assertEqual(status[key], expected[key])
        self.assertEqual(status["decision"], "approved_with_conditions")
        self.assertEqual(status["days_open"], 1.1)
        self.assertEqual(status["exceptions"]["total"], 3)
        self.assertEqual(status["steps_by_actor_type"], {"script": 10, "model": 4, "person": 4})
        self.assertEqual([status["hedged_answers"], status["nudges"]], [1, 1])

    def test_figma_and_asana_days_open_from_appended_rows(self):
        for name, days_open in [("figma", 0.2), ("asana", 0.9)]:
            with self.subTest(sample=name):
                sample = load_sample(name)
                request_id, reply = sample["request_id"], sample["approver_replies"][0]
                requester = sample["people"]["requester"]["name"]
                append_audit_row(request_id, person_row("Request received", requester, sample["messages"][0]["time"]),
                                 self.runs_dir)
                append_audit_row(request_id, person_row("Manager decision", reply["approver"], reply["time"]),
                                 self.runs_dir)
                self.make_ticket(sample, sample["approver_replies"], closed=True)
                status = self.status_of(request_id)
                self.assertEqual(status["decision"], sample["expected"]["status"]["decision"])
                self.assertEqual(status["decision"], "approved")
                self.assertEqual(status["days_open"], sample["expected"]["status"]["days_open"])
                self.assertEqual(status["days_open"], days_open)

    def test_zendesk_before_security_replies_counts_up_to_now(self):
        self.make_zendesk(reply_count=1)
        status = self.status_of("VR-0001", now="2026-10-09T10:00:00-07:00")
        self.assertEqual(status["decision"], "waiting")
        self.assertEqual(status["approvers"]["security"]["decision"], "waiting")
        self.assertEqual(status["days_open"], 1.0)

    def live_ticket(self, **times):
        ticket = create_ticket("VR-0001", load_sample("zendesk")["expected"]["intake"]["fields"], self.tickets_dir)
        ticket["approvers"] = record_decision(ticket["approvers"], "manager", "Daniel Okafor [SYNTHESIZED]",
                                              "approved", LIVE_DECIDED_AT, [])
        ticket.update(times)
        return ticket

    def test_live_vr_0001_counts_from_creation_to_close(self):
        ticket = self.live_ticket(created_at=LIVE_CREATED_AT, closed_at=LIVE_DECIDED_AT)
        self.assertEqual(build_status(ticket, LIVE_AUDIT_ROWS, NOW)["days_open"], 0.6)

    def test_open_ticket_counts_up_to_now_not_last_decision(self):
        ticket = self.live_ticket(created_at=LIVE_CREATED_AT)
        self.assertEqual(build_status(ticket, LIVE_AUDIT_ROWS, "2026-10-10T09:13:00-07:00")["days_open"], 1.5)

    def test_missing_created_at_falls_back_to_first_audit_row(self):
        ticket = self.live_ticket(closed_at="2026-10-09T21:00:00-07:00")
        del ticket["created_at"]
        self.assertEqual(build_status(ticket, LIVE_AUDIT_ROWS, NOW)["days_open"], 0.5)

    def test_append_audit_row_only_appends_and_numbers_steps(self):
        row = person_row("Request received", "Marcus Bell [SYNTHESIZED]", "2026-10-09T10:05:00-07:00")
        append_audit_row("VR-0002", row, self.runs_dir)
        before = audit_path("VR-0002", self.runs_dir).read_bytes()
        append_audit_row("VR-0002", row, self.runs_dir)
        after = audit_path("VR-0002", self.runs_dir).read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))
        self.assertEqual([r["step_id"] for r in read_audit("VR-0002", self.runs_dir)], ["1", "2"])
        for bad in [{"actor_type": "bot"}, {"actor": "  "}, {"timestamp_pt": "2026-10-09T10:05:00"}]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    append_audit_row("VR-0002", {**row, **bad}, self.runs_dir)
        self.assertEqual(audit_path("VR-0002", self.runs_dir).read_bytes(), after)

    def test_command_line_prints_zendesk_summary(self):
        self.make_zendesk()
        result = subprocess.run(
            [sys.executable, "-m", "scripts.status", "--ticket", "VR-0001", "--tickets-dir", str(self.tickets_dir),
             "--runs-dir", str(self.runs_dir), "--now", NOW],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "VR-0001: approved_with_conditions")
        self.assertEqual(lines[1], "manager: Daniel Okafor [SYNTHESIZED], approved, 2026-10-08T16:40:00-07:00")
        self.assertTrue(lines[2].startswith(
            "security: Lena Hoffmann [SYNTHESIZED], approved_with_conditions, 2026-10-09T11:25:00-07:00; conditions: "
        ))
        self.assertEqual(lines[3:], [
            "days open: 1.1",
            "exceptions: 3 (missing intake fields 1, not found pack rows 2, rejections 0)",
            "hedged answers: 1, nudges: 1",
            "steps: 10 script, 4 model, 4 person",
        ])

    def test_new_ticket_without_audit_rows(self):
        sample = load_sample("figma")
        now = "2026-10-09T15:05:00-07:00"
        ticket = create_ticket("VR-0002", sample["expected"]["intake"]["fields"], self.tickets_dir)
        ticket["created_at"] = sample["messages"][0]["time"]
        ticket_path("VR-0002", self.tickets_dir).write_text(json.dumps(ticket, indent=2) + "\n")
        status = build_status(ticket, [], now)
        self.assertEqual(status, {
            "decision": "waiting",
            "approvers": {"manager": {"name": None, "decision": "waiting", "at": None, "conditions": []}},
            "days_open": 0.2,
            "exceptions": {"missing_intake_fields": 0, "not_found_pack_rows": 0, "rejections": 0, "total": 0},
            "hedged_answers": 0,
            "nudges": 0,
            "steps_by_actor_type": {},
        })
        self.runs_dir.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "scripts.status", "--ticket", "VR-0002", "--tickets-dir", str(self.tickets_dir),
             "--runs-dir", str(self.runs_dir), "--now", now],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VR-0002: waiting", result.stdout)
        self.assertIn("days open: 0.2", result.stdout)
        self.assertIn("steps: 0 script, 0 model, 0 person", result.stdout)

    def test_withdrawn_ticket_shows_withdrawn_status(self):
        sample = load_sample("zendesk")
        request_id = sample["request_id"]
        self.make_ticket(sample, [], security=True, counts=ZENDESK_COUNTS)
        ticket = read_ticket(request_id, self.tickets_dir)
        ticket.update({
            "final_decision": "withdrawn",
            "withdrawn_by": "Alice Chan",
            "withdrawn_reason": "no longer needed",
            "closed_at": "2026-10-09T14:30:00-07:00",
        })
        ticket_path(request_id, self.tickets_dir).write_text(json.dumps(ticket, indent=2) + "\n")
        append_audit_row(request_id, person_row("Withdraw", "Alice Chan", "2026-10-09T14:30:00-07:00"),
                         self.runs_dir)
        status = build_status(ticket, read_audit(request_id, self.runs_dir), NOW)
        self.assertEqual(status["decision"], "withdrawn")
        self.assertEqual(status["withdrawn_by"], "Alice Chan")
        self.assertEqual(status["withdrawn_reason"], "no longer needed")
        self.assertEqual(status["closed_at"], "2026-10-09T14:30:00-07:00")
        result = subprocess.run(
            [sys.executable, "-m", "scripts.status", "--ticket", request_id, "--tickets-dir", str(self.tickets_dir),
             "--runs-dir", str(self.runs_dir), "--now", NOW],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "VR-0001: withdrawn")
        self.assertEqual(lines[1], "withdrawn by: Alice Chan")
        self.assertEqual(lines[2], "reason: no longer needed")
        self.assertEqual(lines[3], "closed at: 2026-10-09T14:30:00-07:00")
        self.assertIn("days open:", lines[4])
        self.assertIn("exceptions:", lines[5])


if __name__ == "__main__":
    unittest.main()
