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
                    "ACME_WEBHOOK_KEY_HEADER": "X-Webhook-Key",
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
            self.assertEqual(req["headers"]["Authorization"], "Bearer my-secret")
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


class WebhookSecretNormalizationTest(unittest.TestCase):
    """Test webhook secret normalization for various input formats."""
    
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.runs = str(Path(self.dir) / "runs")
    
    def tearDown(self):
        self.tmp.cleanup()
    
    def run_script_and_get_log(self, secret, header_name="Authorization", cwd=None):
        """Run script with given secret and return log contents."""
        if cwd is None:
            workspace = Path(self.dir) / "workspace"
            workspace.mkdir(exist_ok=True)
            cwd = workspace
        else:
            workspace = cwd
        
        (workspace / ".research_ticket_id").write_text("VR-NORM-TEST")
        
        with MockServerContext() as mock:
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "notify_research_done.py")],
                input='{"status": "completed"}',
                capture_output=True,
                text=True,
                cwd=cwd,
                env={
                    **os.environ,
                    "ACME_WEBHOOK_URL": f"http://127.0.0.1:{mock.port}/webhook",
                    "ACME_WEBHOOK_SECRET": secret,
                    "ACME_WEBHOOK_KEY_HEADER": header_name,
                    "RUNS_DIR": self.runs,
                },
            )
            
            log_file = workspace / ".hook.log"
            log_contents = log_file.read_text() if log_file.exists() else ""
            
            received = MockWebhookHandler.received_requests
            return result, log_contents, received
    
    def test_secret_with_leading_whitespace_is_stripped(self):
        result, log, received = self.run_script_and_get_log("  \t my-secret-key")
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-secret-key")
        
        self.assertNotIn("  \t my-secret-key", log)
    
    def test_secret_with_trailing_whitespace_is_stripped(self):
        result, log, received = self.run_script_and_get_log("my-secret-key\n\r  ")
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-secret-key")
        
        self.assertNotIn("my-secret-key\n\r  ", log)
    
    def test_secret_with_double_quotes_is_stripped(self):
        result, log, received = self.run_script_and_get_log('"my-secret-key"')
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-secret-key")
    
    def test_secret_with_single_quotes_is_stripped(self):
        result, log, received = self.run_script_and_get_log("'my-secret-key'")
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-secret-key")
    
    def test_secret_with_bearer_prefix_is_not_doubled(self):
        result, log, received = self.run_script_and_get_log("Bearer my-secret-key")
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-secret-key")
        self.assertNotIn("Bearer Bearer", received[0]["headers"]["Authorization"])
    
    def test_secret_without_bearer_gets_prefix_for_authorization_header(self):
        result, log, received = self.run_script_and_get_log("my-secret-key")
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-secret-key")
    
    def test_non_authorization_header_does_not_get_bearer_prefix(self):
        result, log, received = self.run_script_and_get_log("my-secret-key", header_name="X-Webhook-Key")
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["X-Webhook-Key"], "my-secret-key")
        self.assertNotIn("Bearer", received[0]["headers"]["X-Webhook-Key"])
    
    def test_complex_normalization_whitespace_quotes_bearer(self):
        result, log, received = self.run_script_and_get_log('  "Bearer my-secret-key"  \n')
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-secret-key")
    
    def test_log_never_contains_full_secret(self):
        secret = "Bearer super-secret-token-abc123xyz"
        result, log, _ = self.run_script_and_get_log(secret)
        
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("super-secret-token-abc123xyz", log)
        self.assertNotIn(secret, log)
        
        self.assertIn("diagnostics=", log)
        self.assertIn("first_4_after_bearer", log)
        self.assertIn("supe", log)
    
    def test_diagnostics_shows_correct_metadata(self):
        secret = '  "Bearer test-key"  '
        result, log, _ = self.run_script_and_get_log(secret)
        
        self.assertEqual(result.returncode, 0)
        self.assertIn('"has_leading_whitespace": true', log)
        self.assertIn('"has_trailing_whitespace": true', log)
        self.assertIn('"has_surrounding_quotes": true', log)
        self.assertIn('"starts_with_bearer": true', log)
        self.assertIn('"first_4_after_bearer": "test"', log)
    
    def test_full_header_line_pasted_as_secret(self):
        """Test the exact VR-0007/VR-0008 failure case: entire header line was pasted."""
        secret = "Authorization: Bearer crsr_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        self.assertEqual(len(secret), 91)
        
        result, log, received = self.run_script_and_get_log(secret)
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        
        sent_header = received[0]["headers"]["Authorization"]
        self.assertEqual(sent_header, "Bearer crsr_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
        self.assertNotIn("Authorization: Bearer Bearer", sent_header)
        self.assertEqual(sent_header.count("Bearer "), 1)
    
    def test_header_line_with_lowercase_authorization(self):
        """Test case-insensitive header name stripping."""
        secret = "authorization: Bearer my-token-xyz"
        result, log, received = self.run_script_and_get_log(secret)
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-token-xyz")
    
    def test_header_line_with_mixed_case(self):
        """Test mixed-case header name stripping."""
        secret = "AuThOrIzAtIoN: Bearer my-token-abc"
        result, log, received = self.run_script_and_get_log(secret)
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["headers"]["Authorization"], "Bearer my-token-abc")


if __name__ == "__main__":
    unittest.main()
