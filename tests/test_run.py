import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.samples import list_samples, load_sample

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKETS_DIR = REPO_ROOT / "tickets"


def run_sample(*args, tmpdir):
    return subprocess.run(
        [sys.executable, "-m", "scripts.run", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, env={**os.environ, "TMPDIR": tmpdir},
    )


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets_before = sorted(TICKETS_DIR.iterdir())

    def tearDown(self):
        self.tmp.cleanup()

    def test_trace_for_each_sample(self):
        zendesk_pack = load_sample("zendesk")["expected"]["pack"]
        want = {
            "zendesk": (
                f"5. [script] Pack check: PASS ({len(zendesk_pack['rows'])} rows, "
                f"{zendesk_pack['check']['not_found']} not_found)",
                "6. [script] Routing: VR-0001: route = manager, security",
            ),
            "figma": (
                "5. [script] Pack check: not built yet",
                "6. [script] Routing: VR-0002: route = manager",
            ),
            "asana": (
                "5. [script] Pack check: not built yet",
                "6. [script] Routing: VR-0003: route = manager",
            ),
        }
        self.assertEqual(sorted(want), sorted(list_samples()))
        for name, (pack_line, route_line) in want.items():
            with self.subTest(sample=name):
                result = run_sample(name, tmpdir=self.tmp.name)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 8)
                self.assertEqual(lines[0], "1. [script] Intake check: complete")
                self.assertEqual(lines[1], "2. [model] Follow-up questions: not built yet")
                self.assertEqual(lines[3], "4. [model] Research: not built yet")
                self.assertEqual(lines[4], pack_line)
                self.assertEqual(lines[5], route_line)
                self.assertEqual(lines[6], "7. [person] Approvals: not built yet")
                self.assertEqual(lines[7], "8. [script] Status and audit: not built yet")

                request_id = load_sample(name)["request_id"]
                ticket = Path(lines[2].removeprefix("3. [script] Ticket: wrote "))
                self.assertEqual(ticket.name, f"{request_id}.json")
                self.assertEqual(ticket.parent.parent, Path(self.tmp.name))
                self.assertTrue(ticket.is_file())
        self.assertEqual(sorted(TICKETS_DIR.iterdir()), self.tickets_before)

    def test_missing_sample_prints_usage_and_fails(self):
        result = run_sample(tmpdir=self.tmp.name)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr, "usage: make run SAMPLE=<zendesk|figma|asana>   e.g. make run SAMPLE=zendesk\n"
        )


if __name__ == "__main__":
    unittest.main()
