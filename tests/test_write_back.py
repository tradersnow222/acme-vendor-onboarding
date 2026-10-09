import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.samples import load_sample
from scripts.ticket import create_ticket, read_ticket, ticket_path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "templates" / "research_pack.json"


class WriteBackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tickets = self.dir / "tickets"
        self.sample = load_sample("zendesk")
        create_ticket("VR-0001", self.sample["expected"]["intake"]["fields"], self.tickets)
        self.ticket_file = ticket_path("VR-0001", self.tickets)
        self.ticket_bytes = self.ticket_file.read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def write_pack(self, request_id, rows):
        path = self.dir / "pack.json"
        path.write_text(json.dumps({"request_id": request_id, "rows": rows}))
        return path

    def run_write_back(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.write_back", *args, "--tickets-dir", str(self.tickets)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_passing_pack_updates_ticket(self):
        before = read_ticket("VR-0001", self.tickets)
        pack = self.write_pack("VR-0001", self.sample["expected"]["pack"]["rows"])
        result = self.run_write_back("--ticket", "VR-0001", "--pack", str(pack))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "VR-0001: pack check PASS (14 rows, 2 not_found); ticket updated\n")
        after = read_ticket("VR-0001", self.tickets)
        self.assertEqual(after["research"]["status"], "done")
        self.assertEqual(after["research"]["pack_check"], {"passed": True, "reasons": [], "not_found": 2})
        self.assertEqual(after["research"]["pack_path"], str(pack))
        self.assertEqual(after["counts"]["exceptions"]["not_found_pack_rows"], 2)
        self.assertEqual(after["counts"]["exceptions"]["not_found_pack_rows"],
                         self.sample["expected"]["status"]["exceptions"]["not_found_pack_rows"])
        expected = copy.deepcopy(before)
        expected["research"] = after["research"]
        expected["counts"]["exceptions"]["not_found_pack_rows"] = 2
        self.assertEqual(after, expected)

    def test_failing_packs_leave_ticket_unchanged(self):
        r1_not_found = copy.deepcopy(self.sample["expected"]["pack"]["rows"])
        r1_not_found[0]["status"] = "not_found"
        packs = {
            "blank template": json.loads(TEMPLATE.read_text())["rows"],
            "zendesk with R1 not_found": r1_not_found,
        }
        for name, rows in packs.items():
            with self.subTest(pack=name):
                pack = self.write_pack("VR-0001", rows)
                result = self.run_write_back("--ticket", "VR-0001", "--pack", str(pack))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout.splitlines()[0], "VR-0001: pack check FAIL")
                self.assertIn("- R1 must be found", result.stdout.splitlines())
                self.assertEqual(self.ticket_file.read_bytes(), self.ticket_bytes)

    def test_pack_for_other_request_is_refused(self):
        pack = self.write_pack("VR-0002", self.sample["expected"]["pack"]["rows"])
        result = self.run_write_back("--ticket", "VR-0001", "--pack", str(pack))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "VR-0001: pack is for 'VR-0002', not VR-0001; ticket not updated\n")
        self.assertEqual(self.ticket_file.read_bytes(), self.ticket_bytes)

    def test_bad_arguments_exit_2_with_example(self):
        pack = self.write_pack("VR-0001", self.sample["expected"]["pack"]["rows"])
        cases = {
            "missing --pack": ["--ticket", "VR-0001"],
            "missing ticket": ["--ticket", "VR-0009", "--pack", str(pack)],
            "missing pack file": ["--ticket", "VR-0001", "--pack", str(self.dir / "nope.json")],
        }
        for name, args in cases.items():
            with self.subTest(case=name):
                result = self.run_write_back(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr.splitlines()[1],
                                 "example: python3 -m scripts.write_back --ticket VR-0001 --pack packs/VR-0001/pack.json")
                self.assertEqual(self.ticket_file.read_bytes(), self.ticket_bytes)


if __name__ == "__main__":
    unittest.main()
