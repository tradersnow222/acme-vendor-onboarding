import csv
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.samples import list_samples, load_sample

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKETS_DIR = REPO_ROOT / "tickets"
RUNS_DIR = REPO_ROOT / "runs"


def run_sample(*args, tmpdir):
    return subprocess.run(
        [sys.executable, "-m", "scripts.run", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, env={**os.environ, "TMPDIR": tmpdir},
    )


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets_before = sorted(TICKETS_DIR.iterdir())
        self.runs_before = sorted(RUNS_DIR.iterdir())

    def tearDown(self):
        self.tmp.cleanup()

    def test_trace_for_each_sample(self):
        zendesk_pack = load_sample("zendesk")["expected"]["pack"]
        want = {
            "zendesk": (
                "2. [script] Follow-up questions: round 1 asked target_start_date, touches_customer_data, "
                "business_owner; complete after 1 round(s)",
                f"5. [script] Pack check: PASS ({len(zendesk_pack['rows'])} rows, "
                f"{zendesk_pack['check']['not_found']} not_found)",
                "6. [script] Routing: VR-0001: route = manager, security",
                "7. [person] Approvals: manager Daniel Okafor [SYNTHESIZED] approved; "
                "security Lena Hoffmann [SYNTHESIZED] approved_with_conditions",
                "exceptions 3, steps 5 script, 1 model, 3 person",
            ),
            "figma": (
                "2. [script] Follow-up questions: none needed",
                "5. [script] Pack check: not built yet",
                "6. [script] Routing: VR-0002: route = manager",
                "7. [person] Approvals: manager Aisha Karim [SYNTHESIZED] approved",
                "exceptions 0, steps 5 script, 1 model, 2 person",
            ),
            "asana": (
                "2. [script] Follow-up questions: round 1 asked business_owner; complete after 1 round(s)",
                "5. [script] Pack check: not built yet",
                "6. [script] Routing: VR-0003: route = manager",
                "7. [person] Approvals: manager Rachel Adeyemi [SYNTHESIZED] approved",
                "exceptions 1, steps 5 script, 1 model, 2 person",
            ),
        }
        self.assertEqual(sorted(want), sorted(list_samples()))
        for name, (followup_line, pack_line, route_line, approvals_line, counts) in want.items():
            with self.subTest(sample=name):
                sample = load_sample(name)
                request_id = sample["request_id"]
                status = sample["expected"]["status"]
                result = run_sample(name, tmpdir=self.tmp.name)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 8)
                self.assertEqual(lines[0], "1. [script] Intake check: complete")
                self.assertEqual(lines[1], followup_line)
                self.assertEqual(
                    lines[3],
                    f"4. [model] Research: dry run, nothing sent; "
                    f"live: python3 -m scripts.launch_research --ticket {request_id} --live",
                )
                self.assertEqual(lines[4], pack_line)
                self.assertEqual(lines[5], route_line)
                self.assertEqual(lines[6], approvals_line)

                ticket = Path(lines[2].removeprefix("3. [script] Ticket: wrote "))
                self.assertEqual(ticket.name, f"{request_id}.json")
                self.assertEqual(ticket.parent.parent, Path(self.tmp.name))
                self.assertTrue(ticket.parent.name.startswith("acme-tickets-"))
                self.assertTrue(ticket.is_file())

                prefix = (
                    f"8. [script] Status and audit: {status['decision']}, days open {status['days_open']}, "
                    f"{counts}; audit "
                )
                self.assertTrue(lines[7].startswith(prefix), lines[7])
                audit = Path(lines[7].removeprefix(prefix))
                self.assertEqual(audit.relative_to(self.tmp.name).parts[1:], (request_id, "audit.csv"))
                self.assertTrue(audit.parent.parent.name.startswith("acme-runs-"))
                with open(audit, newline="") as f:
                    self.assertEqual(next(csv.DictReader(f))["step"], "Request received")
        self.assertEqual(sorted(TICKETS_DIR.iterdir()), self.tickets_before)
        self.assertEqual(sorted(RUNS_DIR.iterdir()), self.runs_before)

    def test_missing_sample_prints_usage_and_fails(self):
        result = run_sample(tmpdir=self.tmp.name)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr, "usage: make run SAMPLE=<zendesk|figma|asana>   e.g. make run SAMPLE=zendesk\n"
        )


if __name__ == "__main__":
    unittest.main()
