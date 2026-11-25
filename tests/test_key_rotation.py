import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.approvals import CONFIG_ENV, load_config
from scripts.samples import load_sample
from scripts.ticket import create_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent


class KeyRotationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name) / "tickets"
        self.runs = Path(self.tmp.name) / "runs"
        self.sample = load_sample("figma")
        create_ticket(self.sample["request_id"], self.sample["expected"]["intake"]["fields"], self.tickets)
        self.rotated = date.fromisoformat(load_config()["api_key_rotated_on"])

    def tearDown(self):
        self.tmp.cleanup()

    def digest(self, day, config_path=None):
        env = os.environ.copy()
        if config_path:
            env[CONFIG_ENV] = str(config_path)
        return subprocess.run(
            [sys.executable, "-m", "scripts.digest", "--tickets-dir", str(self.tickets),
             "--runs-dir", str(self.runs), "--now", f"{day.isoformat()}T12:00:00-07:00"],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env,
        )

    def test_digest_warns_when_the_key_is_80_days_old(self):
        vendor = self.sample["expected"]["intake"]["fields"]["vendor_legal_name"]["value"]
        warning = f"warning: API key rotated on {self.rotated.isoformat()} is 80 days old (90-day policy)\n"

        young = self.digest(self.rotated + timedelta(days=79))
        self.assertEqual(young.returncode, 0, young.stderr)
        self.assertNotIn("warning:", young.stdout)
        self.assertIn(vendor, young.stdout)

        old = self.digest(self.rotated + timedelta(days=80))
        self.assertEqual(old.returncode, 0, old.stderr)
        self.assertIn(vendor, old.stdout)
        self.assertTrue(old.stdout.endswith(warning), old.stdout)

        older = self.digest(self.rotated + timedelta(days=90))
        self.assertIn("is 90 days old (90-day policy)", older.stdout)

        config = json.loads((REPO_ROOT / "config" / "company.json").read_text())
        self.assertIn("api_key_rotated_on is a [SYNTHESIZED] demo date", config["note"])
        config.pop("api_key_rotated_on")
        path = Path(self.tmp.name) / "company.json"
        path.write_text(json.dumps(config))
        quiet = self.digest(self.rotated + timedelta(days=80), path)
        self.assertEqual(quiet.returncode, 0, quiet.stderr)
        self.assertNotIn("warning:", quiet.stdout)
        self.assertIn(vendor, quiet.stdout)
