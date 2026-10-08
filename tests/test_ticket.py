import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.samples import list_samples, load_sample
from scripts.ticket import create_ticket, read_ticket

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
