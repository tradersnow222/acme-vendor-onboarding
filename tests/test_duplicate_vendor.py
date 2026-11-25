import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.samples import load_sample
from scripts.status import audit_path, read_audit
from scripts.ticket import create_ticket, read_ticket
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent


class DuplicateVendorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name) / "tickets"
        self.runs = Path(self.tmp.name) / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def plant(self, request_id, sample_name, **updates):
        sample = load_sample(sample_name)
        fields = json.loads(json.dumps(sample["expected"]["intake"]["fields"]))
        ticket = create_ticket(request_id, fields, self.tickets)
        if updates:
            ticket.update(updates)
            write_ticket(ticket, request_id, self.tickets)
        return sample

    def create(self, sample="zendesk"):
        return subprocess.run(
            [sys.executable, "-m", "scripts.ticket", sample,
             "--dir", str(self.tickets), "--runs-dir", str(self.runs)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_open_ticket_with_same_vendor_warns_and_still_creates(self):
        sample = self.plant("VR-0099", "zendesk")
        vendor = sample["expected"]["intake"]["fields"]["vendor_legal_name"]["value"]
        existing = read_ticket("VR-0099", self.tickets)
        existing["intake"]["vendor_legal_name"]["value"] = vendor.swapcase()
        write_ticket(existing, "VR-0099", self.tickets)

        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, f"warning: {vendor} already has open or approved ticket VR-0099\n")
        ticket = json.loads(result.stdout)
        self.assertEqual(ticket["request_id"], sample["request_id"])
        self.assertEqual(ticket["duplicate_of"], ["VR-0099"])
        self.assertEqual(ticket["intake"]["vendor_legal_name"]["value"], vendor)
        rows = read_audit(sample["request_id"], self.runs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {k: rows[0][k] for k in ("step", "actor_type", "actor", "outcome", "est_cost", "data_label")},
            {"step": "Duplicate vendor", "actor_type": "script", "actor": "scripts.ticket",
             "outcome": "duplicate of VR-0099", "est_cost": "~0", "data_label": "SYNTHESIZED"},
        )

        again = self.create()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stderr, "")
        self.assertEqual(len(read_audit(sample["request_id"], self.runs)), 1)

    def test_closed_approved_ticket_warns(self):
        sample = load_sample("zendesk")
        decision = sample["expected"]["status"]["decision"]
        vendor = sample["expected"]["intake"]["fields"]["vendor_legal_name"]["value"]
        self.plant("VR-0098", "zendesk", closed_at=sample["expected"]["status"]["decided_at"],
                   final_decision=decision)
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, f"warning: {vendor} already has open or approved ticket VR-0098\n")
        self.assertEqual(json.loads(result.stdout)["duplicate_of"], ["VR-0098"])

    def test_rejected_withdrawn_and_other_vendors_do_not_warn(self):
        zendesk = load_sample("zendesk")
        closed_at = zendesk["expected"]["status"]["decided_at"]
        self.plant("VR-0097", "zendesk", closed_at=closed_at, final_decision="rejected")
        self.plant("VR-0096", "zendesk", closed_at=closed_at, final_decision="withdrawn")
        figma = self.plant("VR-0002", "figma")
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        ticket = json.loads(result.stdout)
        self.assertEqual(ticket["request_id"], zendesk["request_id"])
        self.assertNotIn("duplicate_of", ticket)
        self.assertEqual(ticket["intake"]["vendor_legal_name"]["value"],
                         zendesk["expected"]["intake"]["fields"]["vendor_legal_name"]["value"])
        self.assertNotEqual(ticket["intake"]["vendor_legal_name"]["value"],
                            figma["expected"]["intake"]["fields"]["vendor_legal_name"]["value"])
        self.assertFalse(audit_path(zendesk["request_id"], self.runs).exists())
