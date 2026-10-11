import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.approvals import record_decision
from scripts.samples import list_samples, load_sample
from scripts.status import audit_path, read_audit
from scripts.ticket import create_ticket, read_ticket, ticket_path
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent
FIELD_NAMES = ["vendor_legal_name", "website", "touches_customer_data", "business_owner", "target_start_date"]


class TicketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_ticket_from_each_sample(self):
        for name in list_samples():
            with self.subTest(sample=name):
                sample = load_sample(name)
                fields = sample["expected"]["intake"]["fields"]
                create_ticket(sample["request_id"], fields, self.dir)
                ticket = read_ticket(sample["request_id"], self.dir)
                self.assertTrue((self.dir / f"{sample['request_id']}.json").is_file())
                self.assertEqual(ticket["request_id"], sample["request_id"])
                self.assertEqual(sorted(ticket["intake"]), sorted(FIELD_NAMES))
                for field in FIELD_NAMES:
                    self.assertEqual(ticket["intake"][field]["value"], fields[field]["value"])
                self.assertEqual(ticket["research"], {"status": None, "pack_check": None})
                self.assertEqual(ticket["route"], [])
                self.assertEqual(ticket["approvers"]["manager"]["decision"], "waiting")
                self.assertEqual(ticket["approvers"]["manager"]["conditions"], [])
                self.assertEqual(ticket["counts"]["exceptions"],
                                 {"missing_intake_fields": 0, "not_found_pack_rows": 0, "rejections": 0})
                self.assertEqual(ticket["counts"]["hedged_answers"], 0)
                self.assertEqual(ticket["counts"]["nudges"], 0)

    def test_creating_twice_does_not_overwrite(self):
        sample = load_sample("zendesk")
        fields = sample["expected"]["intake"]["fields"]
        first = create_ticket("VR-0001", fields, self.dir)
        changed = dict(fields, website={"value": "https://example.com"})
        second = create_ticket("VR-0001", changed, self.dir)
        on_disk = read_ticket("VR-0001", self.dir)
        self.assertEqual(on_disk["intake"]["website"]["value"], "https://www.zendesk.com")
        self.assertEqual(on_disk["created_at"], first["created_at"])
        self.assertEqual(second, on_disk)

    def test_command_line_creates_ticket_for_sample(self):
        result = subprocess.run(
            [sys.executable, "-m", "scripts.ticket", "figma", "--dir", str(self.dir)],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["request_id"], "VR-0002")
        self.assertEqual(read_ticket("VR-0002", self.dir)["intake"]["vendor_legal_name"]["value"], "Figma, Inc.")


class CloseTicketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets_dir = Path(self.tmp.name) / "tickets"
        self.runs_dir = Path(self.tmp.name) / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def make_ticket(self, name, reply_count=None, security=False):
        sample = load_sample(name)
        ticket = create_ticket(sample["request_id"], sample["expected"]["intake"]["fields"], self.tickets_dir)
        if security:
            ticket["approvers"]["security"] = {"name": None, "decision": "waiting", "at": None, "conditions": []}
        for r in sample["approver_replies"][:reply_count]:
            ticket["approvers"] = record_decision(
                ticket["approvers"], r["role"], r["approver"], r["decision"], r["time"], r["conditions"]
            )
        write_ticket(ticket, sample["request_id"], self.tickets_dir)
        return sample

    def close(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.ticket", *args,
             "--dir", str(self.tickets_dir), "--runs-dir", str(self.runs_dir)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_refuses_while_security_is_waiting(self):
        sample = self.make_ticket("zendesk", 1, security=True)
        before = ticket_path("VR-0001", self.tickets_dir).read_bytes()
        result = self.close("--close", "VR-0001", "--at", sample["expected"]["status"]["decided_at"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "VR-0001: cannot close, still waiting on security\n")
        self.assertEqual(ticket_path("VR-0001", self.tickets_dir).read_bytes(), before)
        self.assertFalse(audit_path("VR-0001", self.runs_dir).exists())

    def test_closes_zendesk_with_conditions_once(self):
        sample = self.make_ticket("zendesk", security=True)
        status = sample["expected"]["status"]
        conditions = sample["approver_replies"][1]["conditions"]
        result = self.close("--close", "VR-0001", "--at", "2026-10-09T11:25:00-07:00")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "VR-0001: closed approved_with_conditions at 2026-10-09T11:25:00-07:00\n"
                                        f"conditions: {'; '.join(conditions)}\n")
        ticket = read_ticket("VR-0001", self.tickets_dir)
        self.assertEqual(ticket["closed_at"], "2026-10-09T11:25:00-07:00")
        self.assertEqual(ticket["final_decision"], status["decision"])
        rows = read_audit("VR-0001", self.runs_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {k: rows[-1][k] for k in ("step", "actor_type", "actor", "timestamp_pt", "outcome", "est_cost", "data_label")},
            {"step": "Close-out", "actor_type": "script", "actor": "scripts.ticket",
             "timestamp_pt": "2026-10-09T11:25:00-07:00",
             "outcome": f"approved_with_conditions; conditions: {'; '.join(conditions)}",
             "est_cost": "~0", "data_label": "SYNTHESIZED"},
        )

        ticket_before = ticket_path("VR-0001", self.tickets_dir).read_bytes()
        audit_before = audit_path("VR-0001", self.runs_dir).read_bytes()
        again = self.close("--close", "VR-0001", "--at", "2026-10-10T09:00:00-07:00")
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stdout,
                         "VR-0001: already closed approved_with_conditions at 2026-10-09T11:25:00-07:00\n")
        self.assertEqual(ticket_path("VR-0001", self.tickets_dir).read_bytes(), ticket_before)
        self.assertEqual(audit_path("VR-0001", self.runs_dir).read_bytes(), audit_before)

    def test_closes_figma_as_approved_without_conditions(self):
        sample = self.make_ticket("figma")
        decided_at = sample["expected"]["status"]["decided_at"]
        result = self.close("--close", "VR-0002", "--at", decided_at)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"VR-0002: closed approved at {decided_at}\n")
        self.assertEqual(read_ticket("VR-0002", self.tickets_dir)["final_decision"], sample["expected"]["status"]["decision"])

    def test_sample_and_close_together_is_a_usage_error(self):
        result = self.close("figma", "--close", "VR-0002")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("give exactly one of", result.stderr)
        self.assertFalse(self.tickets_dir.exists())


class WithdrawTicketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets_dir = Path(self.tmp.name) / "tickets"
        self.runs_dir = Path(self.tmp.name) / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def make_ticket(self, name):
        sample = load_sample(name)
        create_ticket(sample["request_id"], sample["expected"]["intake"]["fields"], self.tickets_dir)
        return sample

    def withdraw(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.ticket", *args,
             "--dir", str(self.tickets_dir), "--runs-dir", str(self.runs_dir)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_withdraw_open_ticket(self):
        sample = self.make_ticket("zendesk")
        result = self.withdraw("--withdraw", "VR-0001", "--by", "Alice Chan",
                               "--reason", "no longer needed", "--at", "2026-10-09T14:30:00-07:00")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "VR-0001: withdrawn by Alice Chan at 2026-10-09T14:30:00-07:00\n"
                                        "reason: no longer needed\n")
        ticket = read_ticket("VR-0001", self.tickets_dir)
        self.assertEqual(ticket["closed_at"], "2026-10-09T14:30:00-07:00")
        self.assertEqual(ticket["final_decision"], "withdrawn")
        self.assertEqual(ticket["withdrawn_by"], "Alice Chan")
        self.assertEqual(ticket["withdrawn_reason"], "no longer needed")
        rows = read_audit("VR-0001", self.runs_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {k: rows[-1][k] for k in ("step", "actor_type", "actor", "timestamp_pt", "outcome", "est_cost", "data_label")},
            {"step": "Withdraw", "actor_type": "person", "actor": "Alice Chan",
             "timestamp_pt": "2026-10-09T14:30:00-07:00",
             "outcome": "withdrawn: no longer needed",
             "est_cost": "~0", "data_label": "SYNTHESIZED"},
        )

    def test_withdraw_refuses_already_closed(self):
        sample = self.make_ticket("figma")
        ticket = read_ticket("VR-0002", self.tickets_dir)
        ticket["closed_at"] = "2026-10-08T10:00:00-07:00"
        ticket["final_decision"] = "approved"
        write_ticket(ticket, "VR-0002", self.tickets_dir)
        before = ticket_path("VR-0002", self.tickets_dir).read_bytes()
        result = self.withdraw("--withdraw", "VR-0002", "--by", "Bob Lee",
                               "--reason", "changed my mind", "--at", "2026-10-09T14:30:00-07:00")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "VR-0002: already closed approved at 2026-10-08T10:00:00-07:00\n")
        self.assertEqual(ticket_path("VR-0002", self.tickets_dir).read_bytes(), before)
        self.assertFalse(audit_path("VR-0002", self.runs_dir).exists())

    def test_withdraw_requires_by_name(self):
        self.make_ticket("zendesk")
        result = self.withdraw("--withdraw", "VR-0001", "--reason", "no longer needed")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--withdraw requires --by <name>", result.stderr)

    def test_withdraw_requires_reason(self):
        self.make_ticket("zendesk")
        result = self.withdraw("--withdraw", "VR-0001", "--by", "Alice Chan")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--withdraw requires --reason <text>", result.stderr)

    def test_withdrawn_treated_as_closed_in_digest(self):
        from scripts.digest import open_tickets
        self.make_ticket("zendesk")
        self.make_ticket("figma")
        self.withdraw("--withdraw", "VR-0001", "--by", "Alice Chan",
                      "--reason", "no longer needed", "--at", "2026-10-09T14:30:00-07:00")
        tickets = open_tickets(self.tickets_dir)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["request_id"], "VR-0002")
