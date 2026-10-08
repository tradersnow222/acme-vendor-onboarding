import subprocess
import sys
import unittest
from pathlib import Path

from scripts.route import inputs_from_sample, route_request
from scripts.samples import list_samples, load_sample

REPO_ROOT = Path(__file__).resolve().parent.parent


def figma_inputs(**overrides):
    inputs = inputs_from_sample(load_sample("figma"))
    inputs.update(overrides)
    return inputs


class RouteSamplesTest(unittest.TestCase):
    def test_each_sample_matches_expected_route(self):
        for name in list_samples():
            with self.subTest(sample=name):
                sample = load_sample(name)
                result = route_request(**inputs_from_sample(sample))
                self.assertEqual(result["route"], sample["expected"]["routing"]["route"])
                self.assertIs(result["blocked"], False)
                self.assertIs(result["mismatch"], False)

    def test_command_line_prints_route(self):
        want = {
            "zendesk": "VR-0001: route = manager, security\n",
            "figma": "VR-0002: route = manager\n",
            "asana": "VR-0003: route = manager\n",
        }
        for name, output in want.items():
            with self.subTest(sample=name):
                run = subprocess.run(
                    [sys.executable, "-m", "scripts.route", name],
                    cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                )
                self.assertEqual(run.stdout, output)


class RouteRulesTest(unittest.TestCase):
    def test_r3_personal_data_overrides_intake_no(self):
        result = route_request(**figma_inputs(r3_shows_customer_data=True))
        self.assertEqual(result["route"], ["manager", "security"])
        self.assertIs(result["mismatch"], True)
        self.assertIs(result["blocked"], False)

    def test_intake_yes_with_r3_no_flags_mismatch_and_keeps_security(self):
        inputs = inputs_from_sample(load_sample("zendesk"))
        inputs["r3_shows_customer_data"] = False
        result = route_request(**inputs)
        self.assertEqual(result["route"], ["manager", "security"])
        self.assertIs(result["mismatch"], True)

    def test_blocked_when_intake_not_passed(self):
        result = route_request(**figma_inputs(intake_passed=False))
        self.assertEqual(result["route"], [])
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_reasons"], ["intake check has not passed"])

    def test_blocked_when_pack_not_passed(self):
        result = route_request(**figma_inputs(pack_passed=False))
        self.assertEqual(result["route"], [])
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_reasons"], ["pack check has not passed"])

    def test_blocked_reasons_list_both_failed_checks(self):
        result = route_request(**figma_inputs(intake_passed=False, pack_passed=False))
        self.assertIs(result["blocked"], True)
        self.assertEqual(
            result["blocked_reasons"],
            ["intake check has not passed", "pack check has not passed"],
        )


if __name__ == "__main__":
    unittest.main()
