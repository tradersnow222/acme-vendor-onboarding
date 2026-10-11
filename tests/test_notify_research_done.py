import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

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


class MockServerContext:
    def __init__(self):
        self.server = None
        self.thread = None
        self.port = None
    
    def __enter__(self):
        MockWebhookHandler.received_requests = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), MockWebhookHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        return self
    
    def __exit__(self, *args):
        self.server.shutdown()


class NotifyResearchDoneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.runs = str(Path(self.dir) / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, stdin_data, env_override=None, cwd=None):
        if env_override is not None:
            env = env_override
        else:
            env = {**os.environ}
        
        script_path = REPO_ROOT / "scripts" / "notify_research_done.py"
        result = subprocess.run(
            [sys.executable, str(script_path)],
            input=stdin_data,
            capture_output=True,
            text=True,
            cwd=cwd or REPO_ROOT,
            env=env,
        )
        return result

    def test_no_env_does_nothing(self):
        env = {k: v for k, v in os.environ.items() 
               if k not in ["ACME_WEBHOOK_URL", "ACME_WEBHOOK_SECRET"]}
        
        result = self.run_script(
            '{"status": "completed"}',
            env_override=env
        )
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("missing ACME_WEBHOOK_URL or ACME_WEBHOOK_SECRET", result.stderr)

    def test_exact_hooks_json_command_with_no_env(self):
        result = subprocess.run(
            ["python3", "scripts/notify_research_done.py"],
            input='{"status": "completed"}',
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={k: v for k, v in os.environ.items() 
                 if k not in ["ACME_WEBHOOK_URL", "ACME_WEBHOOK_SECRET"]},
        )
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("missing ACME_WEBHOOK_URL or ACME_WEBHOOK_SECRET", result.stderr)

    def test_missing_ticket_id_does_nothing(self):
        with MockServerContext() as mock:
            result = self.run_script(
                '{"status": "completed"}',
                env_override={
                    **os.environ,
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{mock.port}/webhook",
                    "ACME_WEBHOOK_SECRET": "secret123",
                }
            )
            
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(MockWebhookHandler.received_requests), 0)
            self.assertIn("no .research_ticket_id file found", result.stderr)

    def test_webhook_sends_correct_payload_and_header(self):
        with MockServerContext() as mock:
            workspace = Path(self.dir) / "workspace"
            workspace.mkdir()
            (workspace / ".research_ticket_id").write_text("VR-0001")
            
            result = self.run_script(
                '{"status": "completed"}',
                env_override={
                    **os.environ,
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{mock.port}/webhook",
                    "ACME_WEBHOOK_SECRET": "secret123",
                    "RUNS_DIR": self.runs,
                },
                cwd=workspace
            )
            
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(MockWebhookHandler.received_requests), 1)
            
            req = MockWebhookHandler.received_requests[0]
            body = json.loads(req["body"])
            
            self.assertEqual(body, {"ticket_id": "VR-0001", "status": "completed"})
            self.assertEqual(req["headers"]["X-Webhook-Key"], "secret123")
            self.assertEqual(req["headers"]["Content-Type"], "application/json")
            
            marker = Path(self.runs) / "VR-0001" / ".webhook_sent"
            self.assertTrue(marker.exists())
            
            self.assertIn("webhook sent successfully for VR-0001", result.stderr)

    def test_custom_webhook_key_header(self):
        with MockServerContext() as mock:
            workspace = Path(self.dir) / "workspace"
            workspace.mkdir()
            (workspace / ".research_ticket_id").write_text("VR-0002")
            
            result = self.run_script(
                '{"status": "failed"}',
                env_override={
                    **os.environ,
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{mock.port}/webhook",
                    "ACME_WEBHOOK_SECRET": "my-secret",
                    "ACME_WEBHOOK_KEY_HEADER": "Authorization",
                    "RUNS_DIR": self.runs,
                },
                cwd=workspace
            )
            
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(MockWebhookHandler.received_requests), 1)
            
            req = MockWebhookHandler.received_requests[0]
            self.assertEqual(req["headers"]["Authorization"], "my-secret")
            self.assertNotIn("X-Webhook-Key", req["headers"])

    def test_second_invocation_does_not_send_again(self):
        with MockServerContext() as mock:
            workspace = Path(self.dir) / "workspace"
            workspace.mkdir()
            (workspace / ".research_ticket_id").write_text("VR-0003")
            
            env = {
                **os.environ,
                "ACME_WEBHOOK_URL": f"http://127.0.0.1:{mock.port}/webhook",
                "ACME_WEBHOOK_SECRET": "secret123",
                "RUNS_DIR": self.runs,
            }
            
            result1 = self.run_script('{"status": "completed"}', env_override=env, cwd=workspace)
            self.assertEqual(result1.returncode, 0)
            self.assertIn("webhook sent successfully for VR-0003", result1.stderr)
            
            result2 = self.run_script('{"status": "completed"}', env_override=env, cwd=workspace)
            self.assertEqual(result2.returncode, 0)
            self.assertIn("webhook already sent for VR-0003", result2.stderr)
            
            self.assertEqual(len(MockWebhookHandler.received_requests), 1)

    def test_network_error_does_not_crash_or_write_marker(self):
        workspace = Path(self.dir) / "workspace"
        workspace.mkdir()
        (workspace / ".research_ticket_id").write_text("VR-0004")
        
        result = self.run_script(
            '{"status": "completed"}',
            env_override={
                **os.environ,
                "ACME_WEBHOOK_URL": "http://127.0.0.1:1/invalid",
                "ACME_WEBHOOK_SECRET": "secret123",
                "RUNS_DIR": self.runs,
            },
            cwd=workspace
        )
        
        self.assertEqual(result.returncode, 0)
        marker = Path(self.runs) / "VR-0004" / ".webhook_sent"
        self.assertFalse(marker.exists())
        self.assertIn("webhook failed for VR-0004", result.stderr)

    def test_log_file_is_written(self):
        workspace = Path(self.dir) / "workspace"
        workspace.mkdir()
        (workspace / ".research_ticket_id").write_text("VR-0005")
        
        with MockServerContext() as mock:
            result = self.run_script(
                '{"status": "completed"}',
                env_override={
                    **os.environ,
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{mock.port}/webhook",
                    "ACME_WEBHOOK_SECRET": "secret123",
                    "RUNS_DIR": self.runs,
                },
                cwd=workspace
            )
            
            self.assertEqual(result.returncode, 0)
            
            log_file = workspace / ".hook.log"
            self.assertTrue(log_file.exists())
            
            log_contents = log_file.read_text()
            self.assertIn("webhook sent successfully for VR-0005", log_contents)
            self.assertIn("status: completed", log_contents)


if __name__ == "__main__":
    unittest.main()
