import json
import os
import ssl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.approval_notice import send_email, slack_escape
from scripts.samples import load_sample
from scripts.ticket import create_ticket, read_ticket
from scripts.write_back import write_ticket

# verification.mdc: call request_approvals the way a user would, on a sample.
# Captured lines are the fake transport. APPROVAL_NOTICE_FAIL is the failing one.
# Neither path opens a socket.

REPO = Path(__file__).resolve().parent.parent
ACME = REPO / "config" / "company.json"
NORTHWIND = REPO / "examples" / "company.sample.json"
BASE = "https://reviews.example.test"
ON = {
    "APPROVAL_SLACK_WEBHOOK_URL": "https://hooks.example.test/services/TEST/TEST/TEST",
    "APPROVAL_SMTP_HOST": "smtp.example.test",
    "APPROVAL_SMTP_PORT": "587",
    "APPROVAL_SMTP_USER": "notices@example.test",
    "APPROVAL_SMTP_PASSWORD": "replace-me",
    "APPROVAL_SMTP_FROM": "notices@example.test",
    "APPROVAL_REVIEW_BASE_URL": BASE,
}
NOTICE_KEYS = list(ON) + ["APPROVAL_NOTICE_CAPTURE", "APPROVAL_NOTICE_FAIL"]


def command_env(extra=None):
    env = {key: value for key, value in os.environ.items()
           if key not in NOTICE_KEYS and key != "CURSOR_API_KEY"}
    if extra:
        env.update(extra)
    return env


def notice_text(vendor, role, request_id, approver, address):
    return (
        f"Vendor: {vendor}\n"
        f"Decision needed: {role} approval\n"
        f"Review: {BASE}/{request_id}\n"
        f"Approver: {approver} <{address}>\n"
    )


class ApprovalNoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.tickets = root / "tickets"
        self.runs = root / "runs"
        self.capture = root / "notices.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, sample_name, request_id):
        sample = load_sample(sample_name)
        create_ticket(request_id, sample["expected"]["intake"]["fields"], self.tickets)
        ticket = read_ticket(request_id, self.tickets)
        ticket["research"]["status"] = "done"
        write_ticket(ticket, request_id, self.tickets)
        return sample

    def request(self, request_id, at, today, env, config=None):
        args = ["--ticket", request_id, "--tickets-dir", str(self.tickets),
                "--runs-dir", str(self.runs), "--at", at, "--today", today]
        if config:
            args += ["--config", str(config)]
        return subprocess.run(
            [sys.executable, "-m", "scripts.request_approvals", *args],
            cwd=REPO, capture_output=True, text=True, env=env,
        )

    def sent(self):
        if not self.capture.exists():
            return []
        return [json.loads(line) for line in self.capture.read_text().splitlines() if line]

    def test_notice_fires_at_approval_step_with_vendor_decision_and_link(self):
        sample = self.prepare("zendesk", "VR-0001")
        config = json.loads(ACME.read_text())
        vendor = sample["expected"]["intake"]["fields"]["vendor_legal_name"]["value"]
        env = command_env({**ON, "APPROVAL_NOTICE_CAPTURE": str(self.capture)})
        result = self.request("VR-0001", "2026-10-08T09:36:00-07:00", "2026-10-08", env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Daniel Okafor [SYNTHESIZED]", result.stdout)
        sent = self.sent()
        self.assertEqual([item["channel"] for item in sent], ["slack", "email", "slack", "email"])
        for role, channel in (("manager", "slack"), ("security", "slack")):
            text = next(item["text"] for item in sent
                        if item["channel"] == channel and role in item["text"])
            self.assertEqual(text, notice_text(
                slack_escape(vendor), role, "VR-0001",
                slack_escape(config["approvers"][role]),
                slack_escape(config["approver_emails"][role])))
            self.assertIn(f"{BASE}/VR-0001", text)
            self.assertIn(f"Decision needed: {role} approval", text)
        for role in ("manager", "security"):
            mail = next(item for item in sent
                        if item["channel"] == "email" and item["to"] == config["approver_emails"][role])
            self.assertEqual(mail["subject"], f"Vendor review: {vendor} - decision needed")
            self.assertEqual(mail["body"], notice_text(
                vendor, role, "VR-0001", config["approvers"][role], config["approver_emails"][role]))
        raw = self.capture.read_text()
        self.assertNotIn("replace-me", raw)
        self.assertNotIn("hooks.example.test", raw)
        for phrase in ("ssn", "ein", "password", "routing number", "bank account", "contract"):
            self.assertNotIn(phrase, raw.lower())

        again = self.request("VR-0001", "2026-10-09T09:36:00-07:00", "2026-10-09", env)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("approvals already requested", again.stdout)
        self.assertEqual(len(self.sent()), 4)

    def test_nothing_is_sent_when_settings_are_off(self):
        self.prepare("zendesk", "VR-0001")
        env = command_env({"APPROVAL_NOTICE_CAPTURE": str(self.capture)})
        result = self.request("VR-0001", "2026-10-08T09:36:00-07:00", "2026-10-08", env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approval requested from", result.stdout)
        self.assertFalse(self.capture.exists())
        self.assertIn("slack skipped, APPROVAL_SLACK_WEBHOOK_URL is unset", result.stderr)
        self.assertIn("email skipped, SMTP settings are unset", result.stderr)
        ticket = read_ticket("VR-0001", self.tickets)
        self.assertEqual(ticket["approvers"]["manager"]["decision"], "waiting")
        self.assertEqual(ticket["approvers"]["manager"]["requested_at"], "2026-10-08T09:36:00-07:00")

    def test_transport_failure_does_not_break_the_review(self):
        self.prepare("zendesk", "VR-0001")
        env = command_env({**ON, "APPROVAL_NOTICE_FAIL": "slack,email"})
        result = self.request("VR-0001", "2026-10-08T09:36:00-07:00", "2026-10-08", env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approval requested from manager (Daniel Okafor [SYNTHESIZED])", result.stdout)
        self.assertIn("slack failed for VR-0001 manager: OSError", result.stderr)
        self.assertIn("email failed for VR-0001 manager: OSError", result.stderr)
        self.assertIn("slack failed for VR-0001 security: OSError", result.stderr)
        self.assertNotIn("URLError", result.stderr)
        self.assertNotIn("gaierror", result.stderr)
        ticket = read_ticket("VR-0001", self.tickets)
        self.assertEqual(ticket["approvers"]["security"]["requested_at"], "2026-10-08T09:36:00-07:00")
        self.assertEqual(ticket["route"], ["manager", "security"])

    def test_company_config_approver_is_used_for_acme_and_northwind(self):
        acme = json.loads(ACME.read_text())
        northwind = json.loads(NORTHWIND.read_text())
        self.assertNotEqual(acme["approvers"]["manager"], northwind["approvers"]["manager"])
        self.assertIn("Priya Shah [SYNTHESIZED]", northwind["approvers"]["manager"])

        sample = self.prepare("figma", "VR-0002")
        vendor = sample["expected"]["intake"]["fields"]["vendor_legal_name"]["value"]
        env = command_env({**ON, "APPROVAL_NOTICE_CAPTURE": str(self.capture)})
        result = self.request("VR-0002", "2026-10-09T14:00:00-07:00", "2026-10-09", env, NORTHWIND)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Priya Shah [SYNTHESIZED]", result.stdout)
        self.assertNotIn("Daniel Okafor", result.stdout)
        sent = self.sent()
        self.assertEqual([item["channel"] for item in sent], ["slack", "email"])
        text = sent[0]["text"]
        self.assertEqual(text, notice_text(
            vendor, "manager", "VR-0002",
            northwind["approvers"]["manager"], northwind["approver_emails"]["manager"]))
        self.assertEqual(sent[1]["to"], northwind["approver_emails"]["manager"])
        self.assertNotIn(acme["approvers"]["manager"], text)
        self.assertNotIn(acme["approver_emails"]["security"], self.capture.read_text())
        self.assertNotIn("Evan Cho", self.capture.read_text())

    def test_slack_escapes_user_text_and_keeps_the_review_link(self):
        self.prepare("zendesk", "VR-0001")
        ticket = read_ticket("VR-0001", self.tickets)
        ticket["intake"]["vendor_legal_name"]["value"] = "<!channel> & Co"
        write_ticket(ticket, "VR-0001", self.tickets)
        config = json.loads(ACME.read_text())
        config["approvers"]["manager"] = "<@U123>"
        config["approver_emails"]["manager"] = "a&b<c>@example.com"
        config_path = Path(self.tmp.name) / "company.json"
        config_path.write_text(json.dumps(config))
        env = command_env({**ON, "APPROVAL_NOTICE_CAPTURE": str(self.capture)})
        result = self.request("VR-0001", "2026-10-08T09:36:00-07:00", "2026-10-08", env, config_path)

        self.assertEqual(result.returncode, 0, result.stderr)
        sent = [item for item in self.sent() if item["channel"] == "slack"]
        self.assertEqual(len(sent), 2)
        manager = next(item["text"] for item in sent if "Decision needed: manager" in item["text"])
        self.assertIn("&lt;!channel&gt; &amp; Co", manager)
        self.assertNotIn("<!channel>", manager)
        self.assertNotIn("<@U123>", manager)
        self.assertIn("&lt;@U123&gt;", manager)
        self.assertIn("a&amp;b&lt;c&gt;@example.com", manager)
        self.assertIn(f"Review: {BASE}/VR-0001\n", manager)
        self.assertEqual(manager, notice_text(
            "&lt;!channel&gt; &amp; Co", "manager", "VR-0001",
            "&lt;@U123&gt;", "a&amp;b&lt;c&gt;@example.com"))
        security = next(item["text"] for item in sent if "Decision needed: security" in item["text"])
        self.assertIn("&lt;!channel&gt; &amp; Co", security)
        self.assertIn(f"Review: {BASE}/VR-0001\n", security)
        mail = next(item for item in self.sent()
                    if item["channel"] == "email" and item["to"] == "a&b<c>@example.com")
        self.assertIn("<!channel> & Co", mail["body"])
        self.assertIn(f"Review: {BASE}/VR-0001\n", mail["body"])


class StartTlsTest(unittest.TestCase):
    def test_starttls_checks_hostname_and_certificate(self):
        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.starttls_context = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def ehlo(self):
                return None

            def starttls(self, *, context=None):
                self.starttls_context = context

            def login(self, user, password):
                return None

            def send_message(self, message):
                return None

        holder = {}

        def factory(*args, **kwargs):
            holder["smtp"] = FakeSMTP(*args, **kwargs)
            return holder["smtp"]

        saved = {key: os.environ.pop(key, None) for key in
                 ("APPROVAL_NOTICE_CAPTURE", "APPROVAL_NOTICE_FAIL")}
        try:
            with mock.patch("scripts.approval_notice.smtplib.SMTP", factory):
                send_email(
                    {"host": "smtp.example.test", "port": 587, "user": "notices@example.test",
                     "password": "replace-me", "from": "notices@example.test"},
                    "approver@example.test", "Vendor review", "body")
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

        context = holder["smtp"].starttls_context
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
