import copy
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.check_pack import check_pack
from scripts.samples import load_sample

REPO_ROOT = Path(__file__).resolve().parent.parent
ZENDESK_PACK = load_sample("zendesk")["expected"]["pack"]


def check_changed(change):
    rows = copy.deepcopy(ZENDESK_PACK["rows"])
    change(rows)
    return check_pack(rows)


def set_field(row_ids, field, value):
    def change(rows):
        for row in rows:
            if row["id"] in row_ids:
                row[field] = value
    return change


class CheckPackTest(unittest.TestCase):
    def test_zendesk_pack_passes_with_expected_not_found_count(self):
        result = check_pack(ZENDESK_PACK["rows"])
        self.assertEqual(result, {"passed": True, "reasons": [], "not_found": ZENDESK_PACK["check"]["not_found"]})

    def test_found_row_without_source_url_fails(self):
        result = check_changed(set_field({"R2"}, "source_urls", []))
        self.assertEqual(result, {"passed": False, "reasons": ["R2 has no source URL"], "not_found": 2})

    def test_r1_not_found_fails(self):
        result = check_changed(set_field({"R1"}, "status", "not_found"))
        self.assertEqual(result, {"passed": False, "reasons": ["R1 must be found"], "not_found": 3})

    def test_r10_all_sub_rows_not_found_fails(self):
        result = check_changed(set_field({"R10a", "R10b", "R10c", "R10d"}, "status", "not_found"))
        self.assertEqual(result, {"passed": False, "reasons": ["R10 must be found"], "not_found": 4})

    def test_missing_r_row_fails(self):
        rows = [row for row in ZENDESK_PACK["rows"] if row["id"] != "R6"]
        result = check_pack(rows)
        self.assertEqual(result, {"passed": False, "reasons": ["R6 has no row"], "not_found": 2})

    def test_bad_date_fails(self):
        result = check_changed(set_field({"R4"}, "checked_date", "10/08/2026"))
        self.assertEqual(
            result, {"passed": False, "reasons": ["R4 has bad checked_date '10/08/2026'"], "not_found": 2}
        )

    def test_command_line_prints_result_for_sample(self):
        run = subprocess.run(
            [sys.executable, "-m", "scripts.check_pack", "zendesk"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout, "VR-0001 zendesk: PASS (14 rows, 2 not_found)\n")
