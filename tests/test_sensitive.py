import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.intake_check import check_intake
from scripts.samples import SAMPLES_DIR, load_sample
from scripts.sensitive import REFERENCE_MESSAGE, SensitiveDataError, find_sensitive
from scripts.status import audit_path
from scripts.ticket import create_ticket

REPO = Path(__file__).resolve().parent.parent
CLEAN = "Call 415-555-0199 or (415) 555-0100 on 2026-10-08 about ticket VR-0001. Zip 94102. W-9 received."


class SensitivePatternTest(unittest.TestCase):
    def test_flags_ssn_ein_routing_and_account(self):
        self.assertIn("ssn", find_sensitive("SSN 123-45-6789"))
        self.assertIn("ssn", find_sensitive("123 45 6789"))
        self.assertIn("ein", find_sensitive("EIN 12-3456789"))
        self.assertIn("tax_id", find_sensitive("TIN 987654321"))
        self.assertIn("routing", find_sensitive("routing number 021000021"))
        self.assertIn("routing", find_sensitive("021000021"))
        self.assertIn("account", find_sensitive("bank account 123456789012"))
        self.assertIn("account", find_sensitive("account number 1234 5678 9012"))

    def test_ignores_phones_dates_ticket_ids_and_urls(self):
        for text in [
            CLEAN,
            "123456789",
            "4408883061530",
            "https://support.zendesk.com/hc/en-us/articles/4408883061530-Sub-processor-Policy",
            "https://example.com/021000021/page",
            "account opened 2026-10-08 for VR-0001",
        ]:
            with self.subTest(text=text):
                self.assertEqual(find_sensitive(text), [])

    def test_samples_and_company_config_are_clean(self):
        paths = list(SAMPLES_DIR.iterdir()) + [REPO / "config" / "company.json"]
        for path in paths:
            if path.is_file() and path.suffix in {".json", ".csv", ".md"}:
                with self.subTest(path=path.name):
                    self.assertEqual(find_sensitive(path.read_text()), [])


class SensitiveIntakeTest(unittest.TestCase):
    def test_intake_rejects_ssn_without_echoing_it(self):
        fields = json.loads(json.dumps(load_sample("figma")["expected"]["intake"]["fields"]))
        secret = "123-45-6789"
        fields["business_owner"]["raw_text"] = f"Owner Jane Doe, SSN {secret}"
        result = check_intake(fields, date(2026, 10, 9))
        self.assertFalse(result["complete"])
        self.assertIn("business_owner", result["sensitive"])
        self.assertIn("W-9 received", result["message"])
        self.assertEqual(result["message"], REFERENCE_MESSAGE)
        self.assertNotIn(secret, json.dumps(result))

    def test_ticket_and_audit_are_not_written(self):
        fields = json.loads(json.dumps(load_sample("figma")["expected"]["intake"]["fields"]))
        fields["business_owner"]["value"] = "Jane Doe SSN 123-45-6789"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SensitiveDataError) as caught:
                create_ticket("VR-0099", fields, tmp)
            self.assertIn("W-9 received", str(caught.exception))
            self.assertFalse((Path(tmp) / "VR-0099.json").exists())

            ticket = create_ticket("VR-0002", load_sample("figma")["expected"]["intake"]["fields"], tmp)
            self.assertEqual(find_sensitive(json.dumps(ticket)), [])
            result = subprocess.run(
                [sys.executable, "-m", "scripts.record_approval", "--ticket", "VR-0002",
                 "--tickets-dir", tmp, "--runs-dir", tmp, "--role", "manager",
                 "--name", "Daniel Okafor", "--decision", "approved",
                 "--quote", "EIN 12-3456789 on file", "--at", "2026-10-09T14:50:00-07:00"],
                cwd=REPO, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("W-9 received", result.stdout)
            self.assertNotIn("12-3456789", result.stdout + result.stderr)
            stored = Path(tmp, "VR-0002.json").read_text()
            self.assertNotIn("12-3456789", stored)
            self.assertFalse(audit_path("VR-0002", tmp).exists())


class SensitiveScriptOutputTest(unittest.TestCase):
    def reply_for(self, pack, log):
        return "```json\n" + json.dumps(pack, indent=2) + "\n```\n\n```csv\n" + log + "```\n"

    def test_figma_ticket_pack_and_audit_are_clean(self):
        sample = load_sample("figma")
        log = (SAMPLES_DIR / "vr-0002-figma-fetch-log.csv").read_text()
        pack = {"request_id": "VR-0002", "rows": sample["expected"]["pack"]["rows"]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tickets, packs, runs = root / "tickets", root / "packs", root / "runs"
            create_ticket("VR-0002", sample["expected"]["intake"]["fields"], tickets)
            reply = root / "reply.md"
            reply.write_text(self.reply_for(pack, log))
            result = subprocess.run(
                [sys.executable, "-m", "scripts.fetch_pack", "--ticket", "VR-0002",
                 "--tickets-dir", str(tickets), "--packs-dir", str(packs), "--runs-dir", str(runs),
                 "--reply-file", str(reply)],
                cwd=REPO, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            written = [path for path in root.rglob("*") if path.is_file() and path != reply]
            self.assertTrue(any(path.name == "pack.json" for path in written))
            self.assertTrue(any(path.name == "audit.csv" for path in written))
            for path in written:
                self.assertEqual(find_sensitive(path.read_text()), [], path.name)

    def test_fetch_pack_refuses_an_ssn_and_writes_no_pack(self):
        sample = load_sample("figma")
        rows = json.loads(json.dumps(sample["expected"]["pack"]["rows"]))
        secret = "123-45-6789"
        rows[0]["value"] = f"Legal name on file, SSN {secret}"
        pack = {"request_id": "VR-0002", "rows": rows}
        log = "url,http_status,fetched_at\nhttps://www.figma.com/legal/tos/,200,2026-10-09T00:00:00+00:00\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tickets, packs = root / "tickets", root / "packs"
            create_ticket("VR-0002", sample["expected"]["intake"]["fields"], tickets)
            reply = root / "reply.md"
            reply.write_text(self.reply_for(pack, log))
            result = subprocess.run(
                [sys.executable, "-m", "scripts.fetch_pack", "--ticket", "VR-0002",
                 "--tickets-dir", str(tickets), "--packs-dir", str(packs), "--runs-dir", str(root / "runs"),
                 "--reply-file", str(reply)],
                cwd=REPO, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("W-9 received", result.stdout)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertFalse((packs / "VR-0002" / "pack.json").exists())


if __name__ == "__main__":
    unittest.main()
