import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from scripts import launch_research
from scripts.fetch_pack import extract_pack
from scripts.samples import load_sample
from scripts.ticket import create_ticket, read_ticket, ticket_path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = "python3 -m scripts.launch_research --ticket VR-0001"
FAKE_KEY = "fake-key-not-real-123"
RESPONSE = {
    "agent": {
        "id": "bc-fake-0001",
        "url": "https://cursor.com/agents/bc-fake-0001",
        "status": "ACTIVE",
        "latestRunId": "run-fake-0001",
    },
    "run": {"id": "run-fake-0001", "status": "CREATING"},
}
EXPECTED_BODY = {
    "prompt": {"text": (
        "Follow .cursor/skills/build-research-pack/SKILL.md for request VR-0001. "
        "The vendor is Zendesk, Inc. (https://www.zendesk.com). "
        "Write only under packs/VR-0001/. Use public pages only. "
        "Do not edit any other file. Do not open a pull request. "
        "End your final reply with packs/VR-0001/pack.json in one ```json fenced block "
        "and packs/VR-0001/fetch_log.csv in one ```csv fenced block whose first line is url,http_status,fetched_at. "
        "Put each fence on its own line and nothing else inside the blocks."
    )},
    "repos": [{"url": "https://github.com/tradersnow222/acme-vendor-onboarding", "startingRef": "main"}],
    "autoCreatePR": False,
}


class LaunchResearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        create_ticket("VR-0001", load_sample("zendesk")["expected"]["intake"]["fields"], self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, "-m", "scripts.launch_research", *args],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env or os.environ,
        )

    def run_live(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"CURSOR_API_KEY": FAKE_KEY}), contextlib.redirect_stdout(out):
            code = launch_research.main(["--ticket", "VR-0001", "--tickets-dir", self.dir, "--live"])
        return code, out.getvalue()

    def test_dry_run_prints_request_without_key_or_ticket_change(self):
        before = ticket_path("VR-0001", self.dir).read_bytes()
        result = self.run_cli("--ticket", "VR-0001", "--tickets-dir", self.dir,
                              env={**os.environ, "CURSOR_API_KEY": FAKE_KEY})
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ["POST https://api.cursor.com/v1/agents",
                     "https://github.com/tradersnow222/acme-vendor-onboarding",
                     '"startingRef": "main"', "build-research-pack", "VR-0001", "Zendesk, Inc."]:
            self.assertIn(text, result.stdout)
        self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1],
                         "Dry run: nothing was sent. Add --live to launch the research agent.")
        self.assertEqual(ticket_path("VR-0001", self.dir).read_bytes(), before)

    def test_live_without_key_fails(self):
        env = {k: v for k, v in os.environ.items() if k != "CURSOR_API_KEY"}
        result = self.run_cli("--ticket", "VR-0001", "--tickets-dir", self.dir, "--live", env=env)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr,
                         "CURSOR_API_KEY is not set; export it or run without --live for a dry run\n")

    def test_missing_or_unknown_ticket_shows_example(self):
        for args in [("--tickets-dir", self.dir), ("--ticket", "VR-9999", "--tickets-dir", self.dir)]:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(EXAMPLE, result.stderr)

    def test_live_records_agent_and_is_idempotent(self):
        intake = load_sample("zendesk")["expected"]["intake"]["fields"]
        with mock.patch.object(launch_research, "send_request", return_value=RESPONSE) as stub:
            code, out = self.run_live()
            self.assertEqual(code, 0)
            self.assertEqual(out, "VR-0001: research agent started: "
                                  "bc-fake-0001 https://cursor.com/agents/bc-fake-0001\n")
            self.assertEqual(stub.call_args.args, (EXPECTED_BODY, FAKE_KEY))

            ticket = read_ticket("VR-0001", self.dir)
            research = ticket["research"]
            self.assertEqual(research["agent_id"], "bc-fake-0001")
            self.assertEqual(research["agent_url"], "https://cursor.com/agents/bc-fake-0001")
            self.assertEqual(research["run_id"], "run-fake-0001")
            self.assertIsNotNone(datetime.fromisoformat(research["launched_at"]).utcoffset())
            self.assertIsNone(research["status"])
            self.assertIsNone(research["pack_check"])
            self.assertEqual(ticket["intake"], intake)

            code, out = self.run_live()
            self.assertEqual(code, 0)
            self.assertEqual(out, "VR-0001: research agent already started: "
                                  "bc-fake-0001 https://cursor.com/agents/bc-fake-0001\n")
            self.assertEqual(stub.call_count, 1)

    def test_prompt_reply_format_matches_fetch_pack(self):
        prompt = launch_research.build_prompt(read_ticket("VR-0001", self.dir))
        for text in ["```json", "```csv", "url,http_status,fetched_at"]:
            self.assertIn(text, prompt)

        pack = {"request_id": "VR-0001", "rows": load_sample("zendesk")["expected"]["pack"]["rows"]}
        fetch_log = "url,http_status,fetched_at\nhttps://www.zendesk.com/trust-center/,200,2026-10-08T09:00:00-07:00\n"
        reply = ("The research pack for VR-0001 is done.\n\n"
                 f"```json\n{json.dumps(pack, indent=2)}\n```\n\n"
                 f"```csv\n{fetch_log}```\n")
        self.assertEqual(extract_pack(reply), (pack, fetch_log))

    def test_help_shows_live_and_examples(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--live", result.stdout)
        self.assertIn(EXAMPLE, result.stdout)
        self.assertIn(f"{EXAMPLE} --live", result.stdout)


if __name__ == "__main__":
    unittest.main()
