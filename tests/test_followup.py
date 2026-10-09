import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.followup import pick_followups
from scripts.intake_check import check_intake
from scripts.samples import load_sample

REPO = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 9)
OWNER_QUESTION = {
    "field": "business_owner",
    "kind": "ask",
    "question": "Who is the business owner? Please give a named person, not a team.",
}


def asana_result(**overrides):
    fields = copy.deepcopy(load_sample("asana")["expected"]["intake"]["fields"])
    for name, field in overrides.items():
        fields[name] = {"from": "requester", "confirmed": False, **field}
    return check_intake(fields, TODAY)


class PickFollowupsTest(unittest.TestCase):
    def test_missing_owner_is_asked_for(self):
        result = pick_followups(asana_result(business_owner={"value": None, "raw_text": ""}), 0)
        self.assertEqual(result, {"questions": [OWNER_QUESTION], "exception": False})

    def test_hedged_customer_data_is_confirmed_after_asks(self):
        result = pick_followups(asana_result(
            business_owner={"value": None, "raw_text": ""},
            touches_customer_data={"value": False, "raw_text": "probably not?"},
        ), 1)
        self.assertEqual(result, {
            "questions": [
                OWNER_QUESTION,
                {
                    "field": "touches_customer_data",
                    "kind": "confirm",
                    "question": "Will this vendor touch Acme customer data, yes or no?",
                },
            ],
            "exception": False,
        })

    def test_brand_only_legal_name_is_not_asked(self):
        result = pick_followups(asana_result(vendor_legal_name={"value": "Asana", "raw_text": "Asana"}), 0)
        self.assertEqual(result, {"questions": [], "exception": False})

    def test_still_incomplete_after_two_rounds_is_an_exception(self):
        result = pick_followups(asana_result(business_owner={"value": None, "raw_text": ""}), 2)
        self.assertEqual(result, {"questions": [], "exception": True})

    def test_research_only_leftovers_after_two_rounds_are_not_an_exception(self):
        result = pick_followups(asana_result(vendor_legal_name={"value": "Asana", "raw_text": "Asana"}), 2)
        self.assertEqual(result, {"questions": [], "exception": False})

    def test_complete_intake_asks_nothing(self):
        self.assertEqual(pick_followups(asana_result(), 1), {"questions": [], "exception": False})

    def test_cli_prints_no_questions_for_final_fields(self):
        output = subprocess.run(
            [sys.executable, "-m", "scripts.followup", "asana"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(output, "VR-0003: follow-up questions: none\n")


class FieldsFlagTest(unittest.TestCase):
    def setUp(self):
        fields = copy.deepcopy(load_sample("asana")["expected"]["intake"]["fields"])
        fields["business_owner"]["value"] = None
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fields_file = Path(tmp.name) / "fields.json"
        self.fields_file.write_text(json.dumps(fields))

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.followup", *args],
            cwd=REPO, capture_output=True, text=True,
        )

    def test_fields_file_asks_for_missing_owner(self):
        result = self.run_cli("--fields", str(self.fields_file), "--today", "2026-10-09", "--rounds", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "ask_for": ["business_owner"],
            "confirm": [],
            "fill_from_research": [],
            "complete": False,
            "questions": [OWNER_QUESTION],
            "exception": False,
        })

    def test_fields_file_after_two_rounds_is_an_exception(self):
        result = self.run_cli("--fields", str(self.fields_file), "--today", "2026-10-09", "--rounds", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["questions"], [])
        self.assertEqual(output["exception"], True)

    def test_missing_fields_file_fails_with_example(self):
        result = self.run_cli("--fields", str(self.fields_file.with_name("missing.json")))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr,
            f"no fields file at {self.fields_file.with_name('missing.json')}\n"
            "example: python3 -m scripts.followup --fields fields.json --today 2026-10-09 --rounds 0\n",
        )


if __name__ == "__main__":
    unittest.main()
