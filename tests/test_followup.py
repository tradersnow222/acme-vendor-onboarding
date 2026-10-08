import copy
import subprocess
import sys
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

    def test_complete_intake_asks_nothing(self):
        self.assertEqual(pick_followups(asana_result(), 1), {"questions": [], "exception": False})

    def test_cli_prints_no_questions_for_final_fields(self):
        output = subprocess.run(
            [sys.executable, "-m", "scripts.followup", "asana"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(output, "VR-0003: follow-up questions: none\n")


if __name__ == "__main__":
    unittest.main()
