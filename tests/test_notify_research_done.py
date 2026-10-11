import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import notify_research_done
from scripts.status import RUNS_DIR, read_audit

REPO_ROOT = Path(__file__).resolve().parent.parent


class MockWebhookHandler(http.server.BaseHTTPRequestHandler):
    received_requests = []
    
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode()
        
        self.received_requests.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        })
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "received"}')
    
    def log_message(self, format, *args):
        pass


class SlowWebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        time.sleep(10)
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, format, *args):
        pass


class NotifyResearchDoneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.runs = str(Path(self.dir) / "runs")
        self.tickets = str(Path(self.dir) / "tickets")
        Path(self.tickets).mkdir(parents=True, exist_ok=True)
        
        ticket = {
            "request_id": "VR-0001",
            "research": {"agent_id": "bc-test-0001"},
        }
        Path(self.tickets, "VR-0001.json").write_text(json.dumps(ticket))

    def tearDown(self):
        self.tmp.cleanup()

    def run_with_stdin(self, stdin_data, env_override=None):
        env = {**os.environ, "RUNS_DIR": self.runs}
        if env_override:
            env.update(env_override)
        
        result = subprocess.run(
            [sys.executable, "-m", "scripts.notify_research_done"],
            input=stdin_data,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        return result

    def test_no_env_does_nothing(self):
        env = {k: v for k, v in os.environ.items() 
               if k not in ["ACME_WEBHOOK_URL", "ACME_WEBHOOK_SECRET"]}
        env["RUNS_DIR"] = self.runs
        
        result = subprocess.run(
            [sys.executable, "-m", "scripts.notify_research_done"],
            input='{"ticket_id": "VR-0001", "status": "completed"}',
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_missing_url_does_nothing(self):
        result = self.run_with_stdin(
            '{"ticket_id": "VR-0001", "status": "completed"}',
            {"ACME_WEBHOOK_SECRET": "secret123"}
        )
        self.assertEqual(result.returncode, 0)

    def test_missing_secret_does_nothing(self):
        result = self.run_with_stdin(
            '{"ticket_id": "VR-0001", "status": "completed"}',
            {"ACME_WEBHOOK_URL": "http://localhost:8888"}
        )
        self.assertEqual(result.returncode, 0)

    def test_webhook_sends_correct_payload_and_header(self):
        MockWebhookHandler.received_requests = []
        server = http.server.HTTPServer(("127.0.0.1", 0), MockWebhookHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        
        try:
            stdin_data = json.dumps({"ticket_id": "VR-0001", "status": "completed"})
            result = self.run_with_stdin(
                stdin_data,
                {
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{port}/webhook",
                    "ACME_WEBHOOK_SECRET": "secret123",
                }
            )
            
            time.sleep(0.2)
            
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(MockWebhookHandler.received_requests), 1)
            
            req = MockWebhookHandler.received_requests[0]
            body = json.loads(req["body"])
            
            self.assertEqual(body, {"ticket_id": "VR-0001", "status": "completed"})
            self.assertEqual(req["headers"]["X-Webhook-Key"], "secret123")
            self.assertEqual(req["headers"]["Content-Type"], "application/json")
            
            audit_rows = read_audit("VR-0001", self.runs)
            self.assertEqual(len(audit_rows), 1)
            self.assertIn("webhook sent", audit_rows[0]["outcome"])
            self.assertEqual(audit_rows[0]["actor"], "scripts.notify_research_done")
        finally:
            server.shutdown()

    def test_custom_webhook_key_header(self):
        MockWebhookHandler.received_requests = []
        server = http.server.HTTPServer(("127.0.0.1", 0), MockWebhookHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        
        try:
            stdin_data = json.dumps({"ticket_id": "VR-0001", "status": "failed"})
            result = self.run_with_stdin(
                stdin_data,
                {
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{port}/webhook",
                    "ACME_WEBHOOK_SECRET": "my-secret",
                    "ACME_WEBHOOK_KEY_HEADER": "Authorization",
                }
            )
            
            time.sleep(0.2)
            
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(MockWebhookHandler.received_requests), 1)
            
            req = MockWebhookHandler.received_requests[0]
            self.assertEqual(req["headers"]["Authorization"], "my-secret")
            self.assertNotIn("X-Webhook-Key", req["headers"])
        finally:
            server.shutdown()

    def test_second_invocation_does_not_send_again(self):
        MockWebhookHandler.received_requests = []
        server = http.server.HTTPServer(("127.0.0.1", 0), MockWebhookHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        
        try:
            env = {
                "ACME_WEBHOOK_URL": f"http://127.0.0.1:{port}/webhook",
                "ACME_WEBHOOK_SECRET": "secret123",
            }
            stdin_data = json.dumps({"ticket_id": "VR-0001", "status": "completed"})
            
            result1 = self.run_with_stdin(stdin_data, env)
            time.sleep(0.2)
            self.assertEqual(result1.returncode, 0)
            
            result2 = self.run_with_stdin(stdin_data, env)
            time.sleep(0.2)
            self.assertEqual(result2.returncode, 0)
            
            self.assertEqual(len(MockWebhookHandler.received_requests), 1)
            
            audit_rows = read_audit("VR-0001", self.runs)
            self.assertEqual(len(audit_rows), 1)
        finally:
            server.shutdown()

    def test_timeout_does_not_raise(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), SlowWebhookHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        
        try:
            stdin_data = json.dumps({"ticket_id": "VR-0001", "status": "completed"})
            result = self.run_with_stdin(
                stdin_data,
                {
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{port}/slow",
                    "ACME_WEBHOOK_SECRET": "secret123",
                }
            )
            
            self.assertEqual(result.returncode, 0)
            
            audit_rows = read_audit("VR-0001", self.runs)
            self.assertEqual(len(audit_rows), 1)
            self.assertIn("webhook failed", audit_rows[0]["outcome"])
        finally:
            server.shutdown()

    def test_ticket_id_from_tickets_dir_fallback(self):
        MockWebhookHandler.received_requests = []
        server = http.server.HTTPServer(("127.0.0.1", 0), MockWebhookHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        
        try:
            stdin_data = json.dumps({"status": "completed"})
            result = self.run_with_stdin(
                stdin_data,
                {
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{port}/webhook",
                    "ACME_WEBHOOK_SECRET": "secret123",
                    "TICKETS_DIR": self.tickets,
                }
            )
            
            time.sleep(0.2)
            
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(MockWebhookHandler.received_requests), 1)
            
            req = MockWebhookHandler.received_requests[0]
            body = json.loads(req["body"])
            self.assertEqual(body["ticket_id"], "VR-0001")
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
