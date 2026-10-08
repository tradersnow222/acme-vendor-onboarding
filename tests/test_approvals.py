import csv
import unittest

from scripts.approvals import is_stale, load_config, overall_decision, record_decision
from scripts.samples import SAMPLES_DIR, list_samples, load_sample


def waiting_approvers(route):
    return {role: {"name": None, "decision": "waiting", "at": None, "conditions": []} for role in route}


def replay(sample, replies):
    approvers = waiting_approvers(sample["expected"]["routing"]["route"])
    for reply in replies:
        approvers = record_decision(
            approvers, reply["role"], reply["approver"], reply["decision"], reply["time"], reply["conditions"]
        )
    return approvers


def zendesk_security_card_sent_at():
    with open(SAMPLES_DIR / "vr-0001-zendesk-audit.csv", newline="") as f:
        rows = {row["step_id"]: row for row in csv.DictReader(f)}
    return rows["14"]["timestamp_pt"]


class ReplaySamplesTest(unittest.TestCase):
    def test_each_sample_ends_at_expected_decision(self):
        want = {"zendesk": "approved_with_conditions", "figma": "approved", "asana": "approved"}
        self.assertEqual(sorted(list_samples()), sorted(want))
        for name, decision in want.items():
            with self.subTest(sample=name):
                sample = load_sample(name)
                approvers = replay(sample, sample["approver_replies"])
                self.assertEqual(overall_decision(approvers), sample["expected"]["status"]["decision"])
                self.assertEqual(overall_decision(approvers), decision)

    def test_zendesk_security_decision_is_recorded_with_conditions(self):
        sample = load_sample("zendesk")
        security = replay(sample, sample["approver_replies"])["security"]
        self.assertEqual(security["name"], "Lena Hoffmann [SYNTHESIZED]")
        self.assertEqual(security["decision"], "approved_with_conditions")
        self.assertEqual(security["at"], "2026-10-09T11:25:00-07:00")
        self.assertEqual(len(security["conditions"]), 4)
        self.assertEqual(security["conditions"][2], "DPA signed")

    def test_zendesk_is_waiting_before_security_replies(self):
        sample = load_sample("zendesk")
        approvers = replay(sample, sample["approver_replies"][:1])
        self.assertEqual(approvers["manager"]["decision"], "approved")
        self.assertEqual(approvers["security"]["decision"], "waiting")
        self.assertEqual(overall_decision(approvers), "waiting")


class RecordRulesTest(unittest.TestCase):
    def setUp(self):
        self.sample = load_sample("figma")
        self.reply = self.sample["approver_replies"][0]
        self.approvers = waiting_approvers(self.sample["expected"]["routing"]["route"])

    def record(self, approvers, role="manager", name=None):
        return record_decision(
            approvers, role, name or self.reply["approver"], self.reply["decision"], self.reply["time"], []
        )

    def test_rejects_blank_anonymous_and_bot_names(self):
        for name in ["", "   ", "Anonymous", "Grok Bot"]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    record_decision(self.approvers, "manager", name, "approved", self.reply["time"], [])
        self.assertEqual(self.approvers["manager"]["decision"], "waiting")

    def test_rejects_recording_twice(self):
        approvers = self.record(self.approvers)
        self.assertEqual(approvers["manager"]["decision"], "approved")
        with self.assertRaises(ValueError):
            self.record(approvers)

    def test_rejects_role_outside_route(self):
        with self.assertRaises(ValueError):
            self.record(self.approvers, role="security", name="Lena Hoffmann [SYNTHESIZED]")


class StaleTest(unittest.TestCase):
    def test_zendesk_security_nudge_is_due_only_after_configured_hours(self):
        sample = load_sample("zendesk")
        approvers = replay(sample, sample["approver_replies"][:1])
        sent_at = zendesk_security_card_sent_at()
        nudge_at = sample["expected"]["status"]["nudges"][0]["at"]
        config = load_config()
        self.assertEqual(config, {"stale_after_hours": 20})
        self.assertIs(is_stale(approvers["security"], sent_at, "2026-10-08T16:40:00-07:00", config), False)
        self.assertIs(is_stale(approvers["security"], sent_at, nudge_at, config), True)
        self.assertEqual(approvers["security"]["decision"], "waiting")
        self.assertEqual(overall_decision(approvers), "waiting")


if __name__ == "__main__":
    unittest.main()
