import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from scripts.approvals import cancel_changed_approvals, content_hash, load_config
from scripts.followup import QUESTIONS as FOLLOWUP_QUESTIONS
from scripts.samples import SAMPLES_DIR, load_sample
from scripts.status import read_audit
from scripts.stale_check import due_approvers
from scripts.ticket import create_ticket, read_ticket
from scripts.tier import QUESTIONS, assign_tier, auto_review_sample, fast_lane_hours, format_mix, low_review_sample, mix_counts
from scripts.verify_tier import apply_pending, evidence_hash, revert_auto, run_verification, verifier_view
from scripts.write_back import write_ticket

REPO = Path(__file__).resolve().parent.parent
CASES = json.loads((SAMPLES_DIR / "tier-cases.json").read_text())
AT = "2026-10-09T14:00:00-07:00"
CLEAN_DOCS = {
    "checked": ["oauth_scopes", "privacy_policy"],
    "oauth_scopes": [],
    "privacy_policy": "Stores no customer data.",
}


def scope_from(changes):
    return {**CASES["clear_low"], **changes}


def auto_config(on=True):
    config = json.loads(json.dumps(load_config()))
    config["tiering"]["auto_decide"] = on
    return config


def evidence_for(ticket, answers, docs, vendor_name=None):
    from scripts.verify_tier import build_evidence
    evidence = build_evidence(ticket, answers, docs)
    if vendor_name:
        evidence["vendor_name"] = vendor_name
    return evidence


class TierPolicyTest(unittest.TestCase):
    def test_questions_are_the_eleven_facts_and_never_ask_for_a_tier(self):
        self.assertEqual(len(QUESTIONS), 11)
        blob = " ".join(prompt for _, prompt in QUESTIONS).lower()
        self.assertNotIn("what tier", blob)
        self.assertNotIn("risk tier", blob)
        self.assertNotIn("what tier", " ".join(FOLLOWUP_QUESTIONS.values()).lower())

    def test_sample_cases_match_expected(self):
        for case in CASES["cases"]:
            with self.subTest(case=case["name"]):
                result = assign_tier(scope_from(case["changes"]))
                expected = case["expected"]
                self.assertEqual(result["tier"], expected["tier"])
                self.assertNotEqual(result["tier"], "low")
                self.assertEqual(result["decision"], expected["decision"])
                self.assertEqual(result["triggers"], expected["triggers"])
                self.assertEqual(result["blank"], expected["blank"])
                self.assertIs(result["auto_reject"], expected["auto_reject"])
                self.assertIs(result["sanction_hit"], expected["sanction_hit"])

    def test_blank_or_not_sure_moves_up_and_never_down(self):
        base = assign_tier(scope_from({}))
        self.assertEqual(base["tier"], "low")
        for value in ("", "not sure", "Not Sure", "unsure"):
            result = assign_tier(scope_from({"q8_spend": value}))
            self.assertEqual(result["tier"], "medium", value)
            self.assertIn("q8_spend", result["blank"])
        self.assertEqual(assign_tier(scope_from({"q4_ai_training": "not sure"}))["tier"], "high")
        self.assertEqual(assign_tier(scope_from({"q9_countries": ""}))["tier"], "high")
        missing = scope_from({})
        del missing["q5_sso_or_oauth"]
        self.assertEqual(assign_tier(missing)["tier"], "medium")

    def test_each_single_trigger_blocks_low(self):
        cases = {
            "pii": {"q2_handles_data": "yes", "q3_data_types": "employee personal data"},
            "phi": {"q2_handles_data": "yes", "q3_data_types": "PHI"},
            "pci": {"q2_handles_data": "yes", "q3_data_types": "PCI"},
            "ai": {"q4_ai_training": "yes"},
            "sso": {"q5_sso_or_oauth": "yes"},
            "write": {"q6_access": "write or API"},
            "privileged": {"q6_access": "production admin"},
            "critical": {"q7_critical_impact": "yes"},
            "spend": {"q8_spend": "10000"},
            "subprocessor": {"q10_subprocessors": "yes"},
            "geography": {"q2_handles_data": "yes", "q3_data_types": "internal", "q9_countries": "CN"},
            "calls": {"q1_purpose": "Tool that records calls"},
        }
        for name, changes in cases.items():
            with self.subTest(trigger=name):
                self.assertNotEqual(assign_tier(scope_from(changes))["tier"], "low")
        self.assertEqual(assign_tier(scope_from({"q8_spend": "9999"}))["tier"], "low")

    def test_internal_only_stays_low_until_the_score_says_otherwise(self):
        internal = scope_from({"q2_handles_data": "yes", "q3_data_types": "internal business information"})
        low = assign_tier(internal)
        self.assertEqual((low["tier"], low["score"], low["triggers"]), ("low", 2, []))
        config = auto_config(False)
        config["tiering"]["score"]["data_internal_only"] = 6
        self.assertEqual(assign_tier(internal, config)["tier"], "high")

    def test_medium_trigger_can_be_turned_off(self):
        drive = scope_from({"q5_sso_or_oauth": "Google Drive", "q8_spend": "free"})
        self.assertNotEqual(assign_tier(drive)["tier"], "low")
        config = auto_config(False)
        config["tiering"]["triggers"]["sso_oauth_or_write_api"]["enabled"] = False
        self.assertEqual(assign_tier(drive, config)["tier"], "low")

    def test_intake_yes_and_a_soc2_note_cannot_lower_the_tier(self):
        denied = assign_tier(scope_from({}), intake_customer_data=True)
        self.assertIn("customer_or_employee_pii", denied["triggers"])
        self.assertNotEqual(denied["tier"], "low")
        high = assign_tier(scope_from({"q3_data_types": "PHI", "q2_handles_data": "yes", "soc2": "yes", "tier": "low"}))
        self.assertEqual(high["tier"], "high")

    def test_blocks_that_are_not_a_confirmed_sanctions_match_stay_with_a_human(self):
        banned = assign_tier(scope_from({"category": "spyware"}))
        self.assertEqual(banned["human_block"], "banned_category")
        self.assertFalse(banned["auto_reject"])
        self.assertEqual(banned["decision"], "human")
        refused = assign_tier(scope_from({
            "q2_handles_data": "yes", "q3_data_types": "internal", "q9_countries": "refuse",
        }))
        self.assertEqual(refused["human_block"], "processing_location_refused")
        self.assertFalse(refused["auto_reject"])
        unsure = assign_tier(scope_from({"q2_handles_data": "yes", "q3_data_types": "internal", "q9_countries": "not sure"}))
        self.assertFalse(unsure["sanction_hit"])
        self.assertNotEqual(unsure["tier"], "low")
        potential = assign_tier(scope_from({}), vendor_name="Potential Example Match")
        self.assertEqual(potential["sanctions"], "potential")
        self.assertFalse(potential["auto_reject"])
        self.assertEqual(potential["decision"], "human")
        self.assertIn("security", potential["route"])

    def test_low_route_is_one_approver_and_the_clock_defaults_to_twenty_hours(self):
        result = assign_tier(scope_from({}))
        self.assertEqual(result["route"], ["manager"])
        config = load_config()
        self.assertEqual(config["stale_after_hours"], 20)
        self.assertEqual(config["tiering"]["fast_lane_hours"], 20)
        self.assertEqual(fast_lane_hours(config), 20)
        self.assertFalse(config["tiering"]["auto_decide"])
        self.assertTrue(config["tiering"]["triggers"]["sso_oauth_or_write_api"]["enabled"])

    def test_fast_lane_timeout_uses_the_configured_hours_and_does_not_approve(self):
        ticket = {
            "approvers": {"manager": {"name": "Daniel Okafor [SYNTHESIZED]", "decision": "waiting",
                                      "at": None, "conditions": [], "requested_at": AT}},
            "tier": {"tier": "low"},
        }
        config = auto_config(False)
        config["stale_after_hours"] = 20
        config["tiering"]["fast_lane_hours"] = 5
        self.assertEqual(due_approvers(ticket, "2026-10-09T18:00:00-07:00", config), [])
        self.assertEqual(len(due_approvers(ticket, "2026-10-09T19:00:00-07:00", config)), 1)
        self.assertEqual(ticket["approvers"]["manager"]["decision"], "waiting")
        medium = {**ticket, "tier": {"tier": "medium"}}
        self.assertEqual(due_approvers(medium, "2026-10-09T19:00:00-07:00", config), [])


class VerificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name) / "tickets"
        self.runs = Path(self.tmp.name) / "runs"
        self.sample = load_sample("figma")
        create_ticket("VR-0002", self.sample["expected"]["intake"]["fields"], self.tickets)

    def tearDown(self):
        self.tmp.cleanup()

    def ticket(self):
        return read_ticket("VR-0002", self.tickets)

    def decide(self, answers, docs, config=None, vendor_name=None, verifiers=None):
        ticket = self.ticket()
        evidence = evidence_for(ticket, answers, docs, vendor_name)
        decision = run_verification(
            ticket, evidence, config or auto_config(True), AT, self.runs, verifiers=verifiers)
        write_ticket(ticket, "VR-0002", self.tickets)
        return decision, ticket

    def test_verifier_catches_google_drive_and_the_call_recorder(self):
        drive_docs = {
            "checked": ["oauth_scopes", "privacy_policy"],
            "oauth_scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            "privacy_policy": "Connects to a file store.",
        }
        decision, ticket = self.decide(scope_from({"q1_purpose": "Free widget", "q8_spend": "free"}), drive_docs)
        self.assertNotEqual(decision["tier"], "low")
        self.assertEqual(decision["action"], "human")
        self.assertTrue(any(item["verdict"] == "FAIL" for item in decision["verdicts"]))
        self.assertNotIn("triage", verifier_view(evidence_for(ticket, {}, drive_docs)))
        text = (self.runs / "VR-0002" / "audit.csv").read_text()
        self.assertIn("evidence_hash=", text)
        self.assertIn("verdict=FAIL", text)
        self.assertIn("verdict does not count", text)
        self.assertIn("oauth scopes contradict", text)
        self.assertFalse(ticket.get("auto_rejected", False))
        self.assertNotEqual(ticket.get("final_decision"), "approved")

        recorder_docs = {
            "checked": ["oauth_scopes", "privacy_policy"],
            "oauth_scopes": [],
            "privacy_policy": "The app records calls to write notes.",
        }
        answers = scope_from({
            "q1_purpose": "AI note taker", "q2_handles_data": "no", "q4_ai_training": "no", "q8_spend": "15",
        })
        decision, ticket = self.decide(answers, recorder_docs)
        self.assertNotEqual(decision["tier"], "low")
        self.assertTrue(any(item["verdict"] == "FAIL" for item in decision["verdicts"]))
        self.assertIn("records calls", (self.runs / "VR-0002" / "audit.csv").read_text())
        self.assertFalse(ticket.get("auto_rejected", False))

    def test_stub_verifiers_cannot_force_an_auto_decision_the_rules_reject(self):
        def stub(evidence, config):
            self.assertNotIn("triage", evidence)
            self.assertNotIn("counts", evidence)
            return {"tier": "low", "decision": "approve", "reasons": ["stub"], "sanction_hit": False}

        docs = dict(CLEAN_DOCS)
        docs["oauth_scopes"] = ["drive.readonly"]
        decision, ticket = self.decide(
            scope_from({"q8_spend": "free"}), docs, verifiers=[("a", stub), ("b", stub)])
        self.assertEqual(decision["action"], "human")
        self.assertNotEqual(decision["tier"], "low")
        self.assertNotEqual(ticket.get("verification", {}).get("status"), "pending_objection")

    def test_auto_reject_only_when_both_verifiers_confirm_sanctions(self):
        benign = [
            scope_from({"q2_handles_data": "yes", "q3_data_types": "customer personal data"}),
            scope_from({"category": "spyware"}),
            scope_from({"q2_handles_data": "yes", "q3_data_types": "internal", "q9_countries": "refuse"}),
        ]
        for answers in benign:
            decision, ticket = self.decide(answers, CLEAN_DOCS)
            self.assertNotEqual(decision["action"], "auto_reject")
            self.assertFalse(ticket.get("auto_rejected", False))
        decision, ticket = self.decide(scope_from({}), CLEAN_DOCS, vendor_name="Potential Example Match")
        self.assertNotEqual(decision["action"], "auto_reject")
        decision, ticket = self.decide(scope_from({}), CLEAN_DOCS, vendor_name="Blocked Example Party")
        self.assertEqual(decision["action"], "auto_reject")
        self.assertTrue(ticket["auto_rejected"])
        self.assertEqual(ticket["final_decision"], "rejected")
        self.assertTrue(all(item["verdict"] == "PASS" and item["sanction_hit"] for item in decision["verdicts"]))

        def deny(evidence, config):
            return {"tier": "high", "decision": "human", "reasons": ["not sure"], "sanction_hit": False}

        decision, _ticket = self.decide(
            scope_from({}), CLEAN_DOCS, vendor_name="Blocked Example Party", verifiers=[("a", deny), ("b", deny)])
        self.assertNotEqual(decision["action"], "auto_reject")

    def test_agreed_low_waits_for_the_named_owner_and_the_kill_switch_stops_it(self):
        decision, ticket = self.decide(scope_from({}), CLEAN_DOCS, config=auto_config(False))
        self.assertEqual(decision["action"], "human")
        self.assertEqual(decision["reason"], "auto_decide is off")
        self.assertNotIn("closed_at", ticket)

        decision, ticket = self.decide(scope_from({}), CLEAN_DOCS, config=auto_config(True))
        self.assertEqual(decision["action"], "pending_objection")
        self.assertEqual(decision["owner_role"], "manager")
        self.assertNotIn("closed_at", ticket)
        self.assertEqual(ticket["approvers"]["manager"]["decision"], "waiting")
        self.assertEqual(ticket["verification"]["triage"]["counts"], False)
        until = datetime.fromisoformat(decision["objection_until"])
        self.assertGreaterEqual((until - datetime.fromisoformat(AT)).total_seconds(), 24 * 3600)

        self.assertFalse(apply_pending(ticket, AT, auto_config(True)))
        self.assertTrue(apply_pending(ticket, (until + timedelta(minutes=1)).isoformat(), auto_config(True)))
        self.assertEqual(ticket["final_decision"], "approved")
        self.assertFalse(apply_pending(self.ticket(), (until + timedelta(hours=2)).isoformat(), auto_config(False)))
        revert_auto(ticket)
        self.assertNotIn("final_decision", ticket)
        with self.assertRaises(ValueError):
            revert_auto(ticket)

    def test_named_owner_can_object_and_the_requester_cannot(self):
        _decision, ticket = self.decide(scope_from({}), CLEAN_DOCS, config=auto_config(True))
        ticket["requester"] = "Riley Quinn [SYNTHESIZED]"
        write_ticket(ticket, "VR-0002", self.tickets)
        common = [sys.executable, "-m", "scripts.tier", "--ticket", "VR-0002", "--at", AT,
                  "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs), "--object"]
        denied = subprocess.run(
            common + ["--by", "Riley Quinn [SYNTHESIZED]", "--reason", "I clear my own request."],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(denied.returncode, 1)
        self.assertIn("requester cannot", denied.stdout)
        owner = load_config()["approvers"]["manager"]
        recorded = subprocess.run(
            common + ["--by", owner, "--reason", "Hold this for Security."],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(recorded.returncode, 0, recorded.stderr + recorded.stdout)
        saved = read_ticket("VR-0002", self.tickets)
        self.assertEqual(saved["verification"]["status"], "human")
        self.assertNotEqual(saved["tier"]["tier"], "low")
        rows = read_audit("VR-0002", self.runs)
        objection = next(row for row in rows if row["step"] == "Objection")
        self.assertEqual(objection["actor_type"], "person")
        self.assertIn("Hold this for Security.", objection["outcome"])
        self.assertIn("evidence_hash=", objection["outcome"])

    def test_three_failed_rounds_stop_and_a_new_snapshot_can_run_again(self):
        def stub(evidence, config):
            return {"tier": "medium", "decision": "human", "reasons": ["stub"], "sanction_hit": False}

        ticket = self.ticket()
        evidence = evidence_for(ticket, scope_from({}), CLEAN_DOCS)
        config = auto_config(True)
        for _ in range(2):
            decision = run_verification(ticket, evidence, config, AT, self.runs, verifiers=[("a", stub), ("b", stub)])
            self.assertFalse(decision["stop"])
        decision = run_verification(ticket, evidence, config, AT, self.runs, verifiers=[("a", stub), ("b", stub)])
        self.assertTrue(decision["stop"])
        self.assertEqual(decision["action"], "human")
        again = run_verification(ticket, evidence, config, AT, self.runs)
        self.assertIn("stopped", again["reason"])
        changed = evidence_for(ticket, scope_from({"q5_sso_or_oauth": "yes"}), CLEAN_DOCS)
        self.assertNotEqual(evidence_hash(evidence), evidence_hash(changed))
        rerun = run_verification(ticket, changed, config, AT, self.runs)
        self.assertIn(evidence_hash(evidence), ticket["verification"]["void_hashes"])
        self.assertTrue(all(item["evidence_hash"] == evidence_hash(changed) for item in rerun["verdicts"]))
        self.assertNotEqual(rerun["tier"], "low")

    def test_scope_change_cancels_a_recorded_approval(self):
        ticket = self.ticket()
        ticket["scope"] = scope_from({})
        ticket["approvers"]["manager"] = {
            "name": "Daniel Okafor [SYNTHESIZED]", "decision": "approved",
            "at": AT, "conditions": [], "hash": content_hash(ticket),
        }
        first = content_hash(ticket)
        ticket["scope"] = scope_from({"q5_sso_or_oauth": "Google Drive"})
        self.assertNotEqual(content_hash(ticket), first)
        cancelled = cancel_changed_approvals(ticket["approvers"], content_hash(ticket))
        self.assertEqual(cancelled[0][0], "manager")
        self.assertEqual(ticket["approvers"]["manager"]["decision"], "waiting")
        self.assertNotEqual(assign_tier(ticket["scope"])["tier"], "low")

    def test_low_timeout_escalates_and_the_requester_cannot_approve(self):
        ticket = self.ticket()
        ticket["tier"] = {"tier": "low"}
        ticket["route"] = ["manager"]
        ticket["requester"] = "Riley Quinn [SYNTHESIZED]"
        ticket["approvers"]["manager"].update({
            "name": "Daniel Okafor [SYNTHESIZED]", "requested_at": AT,
        })
        write_ticket(ticket, "VR-0002", self.tickets)
        early = subprocess.run(
            [sys.executable, "-m", "scripts.stale_check", "--now", "2026-10-10T09:00:00-07:00",
             "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs)],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(early.stdout, "")
        later = "2026-10-10T10:00:00-07:00"
        recorded = subprocess.run(
            [sys.executable, "-m", "scripts.stale_check", "--now", later, "--record",
             "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs)],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertIn("escalate to security", recorded.stdout)
        saved = read_ticket("VR-0002", self.tickets)
        self.assertEqual(saved["approvers"]["manager"]["decision"], "waiting")
        self.assertEqual(saved["approvers"]["security"]["decision"], "waiting")
        self.assertIn("security", saved["route"])
        self.assertIn("silence is not a yes", recorded.stdout + (self.runs / "VR-0002" / "audit.csv").read_text())
        denied = subprocess.run(
            [sys.executable, "-m", "scripts.record_approval", "--ticket", "VR-0002",
             "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
             "--role", "manager", "--name", "Riley Quinn [SYNTHESIZED]",
             "--decision", "approved", "--quote", "I approve my own request.", "--at", later],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(denied.returncode, 1)
        self.assertIn("cannot be the requester", denied.stdout)
        self.assertEqual(read_ticket("VR-0002", self.tickets)["approvers"]["manager"]["decision"], "waiting")

    def test_mix_report_and_weekly_auto_sample(self):
        folder = Path(self.tmp.name) / "mix"
        folder.mkdir()
        for request_id, tier, status in (
            ("VR-0101", "low", None),
            ("VR-0102", "medium", None),
            ("VR-0103", "high", "approved_auto"),
        ):
            ticket = create_ticket(request_id, self.sample["expected"]["intake"]["fields"], folder)
            ticket["tier"] = {"tier": tier, "re_tiered": request_id == "VR-0101"}
            if status:
                ticket["verification"] = {"status": status}
            write_ticket(ticket, request_id, folder)
        tickets = [read_ticket(name, folder) for name in ("VR-0101", "VR-0102", "VR-0103")]
        counts = mix_counts(tickets)
        self.assertEqual(counts, {"low": 1, "medium": 1, "high": 1, "untiered": 0})
        policy = {"low_sample_percent": 0, "auto_sample_percent": 100}
        self.assertEqual(low_review_sample(tickets, policy), ["VR-0101"])
        self.assertEqual(auto_review_sample(tickets, policy), ["VR-0103"])
        self.assertIn("low 1 (33%)", format_mix(counts, ["VR-0101"], ["VR-0103"]))
        result = subprocess.run(
            [sys.executable, "-m", "scripts.tier", "--mix", "--tickets-dir", str(folder)],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tier mix:", result.stdout)
        self.assertIn("weekly auto-decision sample:", result.stdout)

    def test_verifier_module_does_not_call_the_network(self):
        import scripts.verify_tier as verify_tier
        source = inspect.getsource(verify_tier)
        self.assertNotIn("urllib", source)
        self.assertNotIn("openai", source)
        self.assertNotIn("http.client", source)

    def test_command_line_records_the_drive_case_from_the_sample_file(self):
        case = next(item for item in CASES["cases"] if item["name"] == "free_tool_google_drive")
        answers = scope_from(case["changes"])
        answers["q5_sso_or_oauth"] = "no"
        argv = [sys.executable, "-m", "scripts.tier", "--ticket", "VR-0002", "--at", AT,
                "--tickets-dir", str(self.tickets), "--runs-dir", str(self.runs),
                "--oauth", "https://www.googleapis.com/auth/drive.readonly",
                "--privacy", "Connects to a file store.",
                "--checked", "oauth_scopes", "--checked", "privacy_policy"]
        for key, value in answers.items():
            argv.extend(["--answer", f"{key}={value}"])
        result = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("tier low", result.stdout)
        rows = read_audit("VR-0002", self.runs)
        blob = "\n".join(row["outcome"] for row in rows)
        self.assertIn("evidence_hash=", blob)
        self.assertIn("verdict=FAIL", blob)
        self.assertIn(case["expected"]["triggers"][0], blob)
        saved = read_ticket("VR-0002", self.tickets)
        self.assertNotEqual(saved["tier"]["tier"], "low")
        self.assertTrue((self.runs / "VR-0002" / "evidence.json").is_file())
        evidence = json.loads((self.runs / "VR-0002" / "evidence.json").read_text())
        self.assertIn("oauth_scopes", evidence["vendor_docs"])
        self.assertIn("sanctions", evidence)
        self.assertNotIn("triage", evidence)


if __name__ == "__main__":
    unittest.main()
