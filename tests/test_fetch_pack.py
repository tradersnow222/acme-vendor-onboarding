import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import fetch_pack
from scripts.samples import load_sample
from scripts.status import read_audit
from scripts.ticket import create_ticket, read_ticket, ticket_path
from scripts.write_back import write_ticket

REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "fake-key-not-real-123"
AGENT_URL = "https://api.cursor.com/v1/agents/bc-fake-0001"
RUN_URL = "https://api.cursor.com/v1/agents/bc-fake-0001/runs/run-fake-0001"
PASS_LINE = "VR-0001: pack check PASS (14 rows, 2 not_found); ticket updated\n"
FETCH_LOG = "url,http_status,fetched_at\nhttps://www.zendesk.com/trust-center/,200,2026-10-08T09:00:00Z\n"


def build_reply(pack):
    blocks = f"```json\n{json.dumps(pack, indent=2)}\n```\n\n```csv\n{FETCH_LOG}```\n" if pack else ""
    return f"[SYNTHESIZED] Research pack for VR-0001 is done. Two rows are not found.\n\n{blocks}Done.\n"


class FetchPackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tickets = self.dir / "tickets"
        self.packs = self.dir / "packs"
        self.runs = self.dir / "runs"
        sample = load_sample("zendesk")
        ticket = create_ticket("VR-0001", sample["expected"]["intake"]["fields"], self.tickets)
        ticket["research"]["agent_id"] = "bc-fake-0001"
        write_ticket(ticket, "VR-0001", self.tickets)
        self.ticket_bytes = ticket_path("VR-0001", self.tickets).read_bytes()
        self.pack = {"request_id": "VR-0001", "rows": sample["expected"]["pack"]["rows"]}

    def tearDown(self):
        self.tmp.cleanup()

    def dirs(self):
        return ["--tickets-dir", str(self.tickets), "--packs-dir", str(self.packs), "--runs-dir", str(self.runs)]

    def audit(self):
        return [(r["step"], r["actor_type"], r["actor"], r["outcome"], r["data_label"])
                for r in read_audit("VR-0001", self.runs)]

    def run_cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, "-m", "scripts.fetch_pack", "--ticket", "VR-0001", *self.dirs(), *args],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env or os.environ,
        )

    def run_with_reply(self, reply):
        reply_file = self.dir / "reply.md"
        reply_file.write_text(reply)
        return self.run_cli("--reply-file", str(reply_file))

    def run_live(self, run, key=FAKE_KEY):
        responses = {AGENT_URL: {"id": "bc-fake-0001", "latestRunId": "run-fake-0001"}, RUN_URL: run}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(fetch_pack, "send_get", side_effect=lambda url, _: responses[url]) as stub, \
                mock.patch.dict(os.environ, {"CURSOR_API_KEY": key}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fetch_pack.main(["--ticket", "VR-0001", *self.dirs(), "--live"])
        return code, out.getvalue(), err.getvalue(), stub

    def assert_nothing_written(self):
        self.assertFalse(self.packs.exists())
        self.assertEqual(ticket_path("VR-0001", self.tickets).read_bytes(), self.ticket_bytes)

    def test_reply_file_writes_pack_and_is_idempotent(self):
        result = self.run_with_reply(build_reply(self.pack))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, PASS_LINE)
        pack_path = self.packs / "VR-0001" / "pack.json"
        self.assertEqual(json.loads(pack_path.read_text()), self.pack)
        self.assertEqual((self.packs / "VR-0001" / "fetch_log.csv").read_text(), FETCH_LOG)
        self.assertEqual(read_ticket("VR-0001", self.tickets)["research"]["status"], "done")

        again = self.run_with_reply(build_reply(self.pack))
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stdout, f"VR-0001: pack already written back: {pack_path}\n")
        self.assertEqual(self.audit(), [("Research pack built", "model", "Cursor cloud agent reply-file",
                                         "pack check PASS (14 rows, 2 not_found)", "PUBLIC")])

    def test_live_finished_run_writes_back(self):
        code, out, _, stub = self.run_live({"id": "run-fake-0001", "status": "FINISHED", "result": build_reply(self.pack)})
        self.assertEqual(code, 0)
        self.assertEqual(out, PASS_LINE)
        self.assertEqual([c.args for c in stub.call_args_list], [(AGENT_URL, FAKE_KEY), (RUN_URL, FAKE_KEY)])
        self.assertEqual(read_ticket("VR-0001", self.tickets)["research"]["status"], "done")
        self.assertEqual(self.audit(), [("Research pack built", "model", "Cursor cloud agent bc-fake-0001",
                                         "pack check PASS (14 rows, 2 not_found)", "PUBLIC")])

    def test_live_running_run_writes_nothing(self):
        code, out, _, _ = self.run_live({"id": "run-fake-0001", "status": "RUNNING"})
        self.assertEqual(code, 3)
        self.assertEqual(out, "VR-0001: research run run-fake-0001 is RUNNING; try again later\n")
        self.assert_nothing_written()
        self.assertEqual(self.audit(), [])

    def test_failing_pack_check_writes_fail_row(self):
        pack = {**self.pack, "rows": [r for r in self.pack["rows"] if r["id"] != "R2"]}
        result = self.run_with_reply(build_reply(pack))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "VR-0001: pack check FAIL\n- R2 has no row\n")
        self.assertEqual(ticket_path("VR-0001", self.tickets).read_bytes(), self.ticket_bytes)
        self.assertEqual(self.audit(), [("Research pack built", "model", "Cursor cloud agent reply-file",
                                         "pack check FAIL: R2 has no row", "PUBLIC")])

    def test_live_without_key_fails(self):
        code, _, err, stub = self.run_live({}, key="")
        self.assertEqual(code, 2)
        self.assertEqual(err, fetch_pack.NO_KEY + "\n")
        stub.assert_not_called()

    def test_dry_run_sends_nothing_and_hides_key(self):
        result = self.run_cli(env={**os.environ, "CURSOR_API_KEY": FAKE_KEY})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"GET {AGENT_URL}\n", result.stdout)
        self.assertIn(f"GET {AGENT_URL}/runs/<latestRunId>\n", result.stdout)
        self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)
        self.assert_nothing_written()

    def test_bad_replies_write_nothing(self):
        cases = {
            "no json block": (build_reply(None), "VR-0001: no pack.json block in the agent's final reply\n"),
            "pack for VR-0002": (build_reply({**self.pack, "request_id": "VR-0002"}),
                                 "VR-0001: pack is for 'VR-0002', not VR-0001; nothing written\n"),
        }
        for name, (reply, expected) in cases.items():
            with self.subTest(case=name):
                result = self.run_with_reply(reply)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, expected)
                self.assert_nothing_written()


if __name__ == "__main__":
    unittest.main()
