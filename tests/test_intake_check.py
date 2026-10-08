import copy
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

from scripts.intake_check import check_intake
from scripts.samples import list_samples, load_sample

REPO = Path(__file__).resolve().parent.parent
FIRST_MESSAGE_OVERRIDES = {
    "zendesk": {
        "vendor_legal_name": {"value": "Zendesk", "raw_text": "Zendesk", "from": "requester", "confirmed": False},
        "touches_customer_data": {"value": True, "raw_text": "I guess yes it touches customer data", "from": "requester", "confirmed": False},
        "target_start_date": {"value": "asap", "raw_text": "asap", "from": "requester", "confirmed": False},
    },
    "figma": {},
    "asana": {
        "business_owner": {"value": None, "raw_text": "", "from": "requester", "confirmed": False},
    },
}


def request_day(sample):
    return date.fromisoformat(sample["messages"][0]["time"][:10])


def first_message_fields(name):
    sample = load_sample(name)
    fields = copy.deepcopy(sample["expected"]["intake"]["fields"])
    fields.update(copy.deepcopy(FIRST_MESSAGE_OVERRIDES[name]))
    return fields


class SampleIntakeTest(unittest.TestCase):
    def test_final_fields_are_complete(self):
        for name in list_samples():
            with self.subTest(sample=name):
                sample = load_sample(name)
                result = check_intake(sample["expected"]["intake"]["fields"], request_day(sample))
                self.assertEqual(result, {"ask_for": [], "confirm": [], "fill_from_research": [], "complete": True})

    def test_after_first_message_matches_expected(self):
        for name in list_samples():
            with self.subTest(sample=name):
                sample = load_sample(name)
                expected = sample["expected"]["intake"]["after_first_message"]
                result = check_intake(first_message_fields(name), request_day(sample))
                self.assertEqual({key: result[key] for key in expected}, expected)
                self.assertEqual(result["complete"], name == "figma")

    def test_cli_prints_result_for_sample(self):
        output = subprocess.run(
            [sys.executable, "-m", "scripts.intake_check", "zendesk", "--today", "2026-10-08"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(
            output,
            "VR-0001: intake complete\n  ask for: none\n  confirm: none\n  fill from research: none\n",
        )


class RuleTableTest(unittest.TestCase):
    TODAY = date(2026, 10, 8)

    def check_with(self, name, **field):
        fields = copy.deepcopy(load_sample("figma")["expected"]["intake"]["fields"])
        fields[name] = {"from": "requester", "confirmed": True, **field}
        return check_intake(fields, self.TODAY)

    def test_brand_only_legal_name_without_source_goes_to_research(self):
        result = self.check_with("vendor_legal_name", value="Figma", raw_text="Figma")
        self.assertEqual(result["fill_from_research"], ["vendor_legal_name"])
        self.assertEqual(result["ask_for"], [])
        self.assertFalse(result["complete"])

    def test_asap_start_date_is_asked_for(self):
        result = self.check_with("target_start_date", value="asap", raw_text="asap")
        self.assertEqual(result["ask_for"], ["target_start_date"])
        self.assertFalse(result["complete"])

    def test_past_start_date_is_asked_for(self):
        result = self.check_with("target_start_date", value="2026-10-07", raw_text="Oct 7")
        self.assertEqual(result["ask_for"], ["target_start_date"])

    def test_start_date_today_is_valid(self):
        result = self.check_with("target_start_date", value="2026-10-08", raw_text="today")
        self.assertTrue(result["complete"])

    def test_me_as_owner_is_asked_for(self):
        result = self.check_with("business_owner", value="me", raw_text="me")
        self.assertEqual(result["ask_for"], ["business_owner"])

    def test_team_as_owner_is_asked_for(self):
        result = self.check_with("business_owner", value="the design team", raw_text="the design team")
        self.assertEqual(result["ask_for"], ["business_owner"])

    def test_hedged_unconfirmed_customer_data_needs_confirming(self):
        result = self.check_with("touches_customer_data", value=True, raw_text="I guess yes", confirmed=False)
        self.assertEqual(result["confirm"], ["touches_customer_data"])
        self.assertEqual(result["ask_for"], [])
        self.assertFalse(result["complete"])

    def test_not_sure_customer_data_is_asked_for(self):
        result = self.check_with("touches_customer_data", value="not sure", raw_text="not sure")
        self.assertEqual(result["ask_for"], ["touches_customer_data"])


if __name__ == "__main__":
    unittest.main()
