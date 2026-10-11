import contextlib
import copy
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.check_pack import check_pack, main
from scripts.samples import SAMPLES_DIR, load_sample, sample_fetch_log

REPO_ROOT = Path(__file__).resolve().parent.parent
ZENDESK_PACK = load_sample("zendesk")["expected"]["pack"]
FIGMA_PACK = load_sample("figma")["expected"]["pack"]
FIGMA_LOG = SAMPLES_DIR / "vr-0002-figma-fetch-log.csv"
TOS_URL = "https://www.figma.com/legal/tos/"
TOS_LINE = f"{TOS_URL},200,2026-10-09T00:36:40+00:00\n"


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

    def check_figma_with_log(self, log_text):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "fetch_log.csv"
            log.write_text(log_text)
            return check_pack(FIGMA_PACK["rows"], log)

    def test_figma_pack_passes_when_every_link_is_logged_with_200(self):
        result = check_pack(FIGMA_PACK["rows"], FIGMA_LOG)
        self.assertEqual(result, {"passed": True, "reasons": [], "not_found": FIGMA_PACK["check"]["not_found"]})

    def test_link_missing_from_fetch_log_fails_and_names_row(self):
        log_text = FIGMA_LOG.read_text()
        self.assertIn(TOS_LINE, log_text)
        result = self.check_figma_with_log(log_text.replace(TOS_LINE, ""))
        self.assertEqual(result, {
            "passed": False, "reasons": [f"R1 cites {TOS_URL} without an HTTP 200 in the fetch log"], "not_found": 0,
        })

    def test_link_logged_with_non_200_fails_and_names_row(self):
        log_text = FIGMA_LOG.read_text()
        self.assertIn(TOS_LINE, log_text)
        result = self.check_figma_with_log(log_text.replace(TOS_LINE, TOS_LINE.replace(",200,", ",404,")))
        self.assertEqual(result, {
            "passed": False, "reasons": [f"R1 cites {TOS_URL} without an HTTP 200 in the fetch log"], "not_found": 0,
        })

    def test_command_line_checks_the_sample_fetch_log(self):
        self.assertEqual(sample_fetch_log("VR-0002"), FIGMA_LOG)
        self.assertIsNone(sample_fetch_log("VR-0001"))
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "fetch_log.csv"
            log.write_text(FIGMA_LOG.read_text().replace(TOS_LINE, ""))
            with mock.patch("scripts.check_pack.sample_fetch_log", return_value=log), contextlib.redirect_stdout(out):
                code = main(["figma"])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), "VR-0002 figma: FAIL (12 rows, 0 not_found)\n"
                                         f"- R1 cites {TOS_URL} without an HTTP 200 in the fetch log\n")

    def test_command_line_prints_result_for_sample(self):
        run = subprocess.run(
            [sys.executable, "-m", "scripts.check_pack", "zendesk"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout, "VR-0001 zendesk: PASS (14 rows, 2 not_found)\n")
