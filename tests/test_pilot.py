import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from scripts.samples import load_sample
from scripts.ticket import read_ticket

REPO = Path(__file__).resolve().parent.parent
SAMPLE_CONFIG = REPO / "examples" / "company.sample.json"
REQUEST_AT = "2026-10-09T14:00:00-07:00"


def command_env(config_path):
    env = {key: value for key, value in os.environ.items() if key != "CURSOR_API_KEY"}
    env.pop("VENDOR_ONBOARDING_CONFIG", None)
    if config_path:
        env["VENDOR_ONBOARDING_CONFIG"] = str(config_path)
    return env


def run_script(args, env, cwd):
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=cwd, capture_output=True, text=True, env=env,
    )


class PilotDocsTest(unittest.TestCase):
    def test_readme_links_the_pilot_and_the_config_env(self):
        readme = (REPO / "README.md").read_text()
        self.assertIn("[PILOT.md](PILOT.md)", readme)
        self.assertIn("VENDOR_ONBOARDING_CONFIG", readme)
        self.assertTrue(readme.rstrip().endswith("Built by Matt Snow on Grok Bot."))

    def test_pilot_and_data_handling_state_the_limits(self):
        pilot = (REPO / "PILOT.md").read_text()
        handling = (REPO / "DATA-HANDLING.md").read_text()
        config = json.loads(SAMPLE_CONFIG.read_text())
        for text in (pilot, handling):
            for phrase in [
                "vendor name", "contact", "product", "use case", "review notes",
                "bank details", "EIN/tax IDs", "SSNs", "passwords", "contract PDFs",
                "customer data", "tests/test_sensitive.py",
            ]:
                self.assertIn(phrase, text)
        self.assertIn("cp examples/company.sample.json config/company.json", pilot)
        self.assertIn('export VENDOR_ONBOARDING_CONFIG="$PWD/examples/company.sample.json"', pilot)
        self.assertIn("python3 -m scripts.intake_check figma --today 2026-10-09", pilot)
        self.assertIn("python3 -m scripts.record_approval", pilot)
        self.assertIn(config["company_name"], pilot)
        self.assertIn(config["approvers"]["manager"], pilot)
        self.assertNotIn("CURSOR_API_KEY=", pilot)


class PilotReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.tickets = root / "tickets"
        self.packs = root / "packs"
        self.runs = root / "runs"
        self.tickets.mkdir()
        self.packs.mkdir()
        self.runs.mkdir()
        self.config = json.loads(SAMPLE_CONFIG.read_text())
        self.env = command_env(SAMPLE_CONFIG)

    def tearDown(self):
        self.tmp.cleanup()

    def script(self, *args):
        result = run_script(args, self.env, REPO)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_sample_config_review_uses_northwind_not_acme(self):
        demo = subprocess.run(
            [sys.executable, "-c",
             "from scripts.approvals import load_config; print(load_config()['company_name'])"],
            cwd=REPO, capture_output=True, text=True, env=command_env(None),
        )
        self.assertEqual(demo.stdout.strip(), "Acme", demo.stderr)
        loaded = subprocess.run(
            [sys.executable, "-c",
             "from scripts.approvals import load_config\n"
             "config = load_config()\n"
             "print(config['company_name'])\n"
             "print(config['stale_after_hours'])\n"
             "print(config['approvers']['manager'])"],
            cwd=REPO, capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertEqual(
            loaded.stdout.splitlines(),
            ["Northwind Goods", "48", self.config["approvers"]["manager"]],
        )
        self.assertNotEqual(self.config["company_name"], "Acme")
        self.assertGreater(self.config["stale_after_hours"], 20)
        self.assertNotIn("Daniel Okafor", self.config["approvers"]["manager"])

        intake = self.script("scripts.intake_check", "figma", "--today", "2026-10-09")
        self.assertIn("VR-0002: intake complete", intake.stdout)

        self.script("scripts.ticket", "figma", "--dir", str(self.tickets))
        launch = self.script(
            "scripts.launch_research", "--ticket", "VR-0002",
            "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
        )
        self.assertIn("Dry run: nothing was sent.", launch.stdout)

        sample = load_sample("figma")
        pack = {"request_id": sample["request_id"], "rows": sample["expected"]["pack"]["rows"]}
        log = (REPO / "data" / "samples" / "vr-0002-figma-fetch-log.csv").read_text()
        reply = self.runs / "reply.md"
        reply.write_text("```json\n" + json.dumps(pack, indent=2) + "\n```\n\n```csv\n" + log + "```\n")
        fetched = self.script(
            "scripts.fetch_pack", "--ticket", "VR-0002",
            "--tickets-dir", str(self.tickets), "--packs-dir", str(self.packs),
            "--runs-dir", str(self.runs), "--reply-file", str(reply),
        )
        self.assertIn("pack check PASS", fetched.stdout)

        requested = self.script(
            "scripts.request_approvals", "--ticket", "VR-0002",
            "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
            "--at", REQUEST_AT, "--today", "2026-10-09",
        )
        self.assertIn(self.config["approvers"]["manager"].split(",")[0], requested.stdout)
        self.assertNotIn("Daniel Okafor", requested.stdout)
        self.assertNotIn("Lena Hoffmann", requested.stdout)
        ticket = read_ticket("VR-0002", self.tickets)
        self.assertEqual(ticket["route"], ["manager"])
        self.assertEqual(ticket["approvers"]["manager"]["name"], self.config["approvers"]["manager"])

        digest = self.script(
            "scripts.digest", "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
            "--now", "2026-10-09T14:10:00-07:00",
        )
        self.assertTrue(digest.stdout.startswith(
            "Northwind Goods vendor digest 2026-10-09: 1 open request(s)\n"))
        self.assertNotIn("Acme", digest.stdout)

        # Inside the sample window (48h) and past the Acme demo window (20h).
        stale_at = (datetime.fromisoformat(REQUEST_AT) + timedelta(
            hours=self.config["stale_after_hours"] - 1)).isoformat()
        stale = self.script(
            "scripts.stale_check", "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
            "--now", stale_at,
        )
        self.assertEqual(stale.stdout, "")
        self.assertNotIn("nudged_at", read_ticket("VR-0002", self.tickets)["approvers"]["manager"])

        recorded = self.script(
            "scripts.record_approval", "--ticket", "VR-0002", "--role", "manager",
            "--name", self.config["approvers"]["manager"], "--decision", "approved",
            "--quote", "Approved for the 90-day pilot.", "--at", "2026-10-09T14:50:00-07:00",
            "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
        )
        self.assertIn("overall approved", recorded.stdout)
        self.script(
            "scripts.ticket", "--close", "VR-0002", "--at", "2026-10-09T14:51:00-07:00",
            "--dir", str(self.tickets), "--runs-dir", str(self.runs),
        )
        status = self.script(
            "scripts.status", "--ticket", "VR-0002",
            "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
            "--now", "2026-10-09T14:51:00-07:00",
        )
        self.assertTrue(status.stdout.startswith("VR-0002: approved\n"))
        self.assertIn(self.config["approvers"]["manager"], status.stdout)
        self.assertNotIn("Daniel Okafor", status.stdout)
        closed = read_ticket("VR-0002", self.tickets)
        self.assertEqual(closed["final_decision"], sample["expected"]["status"]["decision"])
        self.assertEqual(closed["final_decision"], "approved")
        audit = (self.runs / "VR-0002" / "audit.csv").read_text()
        self.assertIn(self.config["approvers"]["manager"], audit)
        self.assertNotIn("Daniel Okafor", audit)


if __name__ == "__main__":
    unittest.main()
