#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TIMEOUT_SECONDS = 5
LOG_FILE = Path(".hook.log")


def log_message(message):
    timestamp = datetime.now(timezone.utc).isoformat()
    log_line = f"[{timestamp}] {message}\n"
    
    print(log_line.rstrip(), file=sys.stderr)
    
    try:
        with LOG_FILE.open("a") as f:
            f.write(log_line)
    except Exception:
        pass


def read_hook_input():
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def find_ticket_id():
    ticket_marker = Path(".research_ticket_id")
    if ticket_marker.exists():
        return ticket_marker.read_text().strip()
    return None


def get_marker_path(ticket_id):
    runs_dir = os.environ.get("RUNS_DIR", "runs")
    return Path(runs_dir) / ticket_id / ".webhook_sent"


def check_already_sent(ticket_id):
    return get_marker_path(ticket_id).exists()


def write_marker(ticket_id):
    marker_path = get_marker_path(ticket_id)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("")


def normalize_webhook_secret(secret, header_name):
    """
    Normalize webhook secret by:
    1. Stripping leading header name (e.g. 'Authorization:') if present
    2. Stripping whitespace and quotes
    3. For Authorization header, ensuring exactly one Bearer prefix
    """
    normalized = secret.strip()
    
    # Strip leading header name if present (case-insensitive)
    # e.g. "Authorization: Bearer token" -> "Bearer token"
    header_prefix = f"{header_name}:"
    if normalized.lower().startswith(header_prefix.lower()):
        normalized = normalized[len(header_prefix):].strip()
    
    # Strip quotes and whitespace
    normalized = normalized.strip('"').strip("'").strip()
    
    # For Authorization header, ensure exactly one Bearer prefix
    if header_name == "Authorization":
        if not normalized.startswith("Bearer "):
            normalized = f"Bearer {normalized}"
    
    return normalized


def redact_for_log(secret):
    """
    Create a redacted version of the secret for logging diagnostics.
    Shows: length, Bearer prefix presence, whitespace, quotes, first 4 chars after Bearer.
    """
    stripped_ws = secret.strip()
    stripped = stripped_ws.strip('"').strip("'").strip()
    
    diagnostics = {
        "length": len(secret),
        "has_leading_whitespace": secret != secret.lstrip(),
        "has_trailing_whitespace": secret != secret.rstrip(),
        "has_surrounding_quotes": (stripped_ws.startswith('"') or stripped_ws.startswith("'")) and 
                                  (stripped_ws.endswith('"') or stripped_ws.endswith("'")),
        "starts_with_bearer": stripped.startswith("Bearer "),
    }
    
    if stripped.startswith("Bearer "):
        prefix_end = len("Bearer ")
        first_chars = stripped[prefix_end:prefix_end+4] if len(stripped) > prefix_end else ""
        diagnostics["first_4_after_bearer"] = first_chars
    else:
        diagnostics["first_4_chars"] = stripped[:4] if len(stripped) >= 4 else stripped
    
    return diagnostics


def send_webhook(ticket_id, status, webhook_url, webhook_secret, webhook_key_header):
    normalized_secret = normalize_webhook_secret(webhook_secret, webhook_key_header)
    
    log_diagnostics = redact_for_log(webhook_secret)
    log_message(f"notify_research_done: sending webhook for {ticket_id}, header={webhook_key_header}, diagnostics={json.dumps(log_diagnostics)}")
    
    payload = json.dumps({"ticket_id": ticket_id, "status": status}).encode()
    headers = {
        "Content-Type": "application/json",
        webhook_key_header: normalized_secret,
    }
    
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers=headers,
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='replace')[:300]
        log_message(f"notify_research_done: HTTP {e.code} response body: {error_body}")
        raise


def main():
    webhook_url = os.environ.get("ACME_WEBHOOK_URL")
    webhook_secret = os.environ.get("ACME_WEBHOOK_SECRET")
    
    if not webhook_url or not webhook_secret:
        log_message("notify_research_done: missing ACME_WEBHOOK_URL or ACME_WEBHOOK_SECRET, skipping")
        sys.exit(0)
    
    webhook_key_header = os.environ.get("ACME_WEBHOOK_KEY_HEADER", "X-Webhook-Key")
    
    hook_input = read_hook_input()
    status = hook_input.get("status", "completed")
    
    ticket_id = find_ticket_id()
    if not ticket_id:
        log_message("notify_research_done: no .research_ticket_id file found, skipping")
        sys.exit(0)
    
    if check_already_sent(ticket_id):
        log_message(f"notify_research_done: webhook already sent for {ticket_id}, skipping")
        sys.exit(0)
    
    try:
        send_webhook(ticket_id, status, webhook_url, webhook_secret, webhook_key_header)
        write_marker(ticket_id)
        log_message(f"notify_research_done: webhook sent successfully for {ticket_id} (status: {status})")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        log_message(f"notify_research_done: webhook failed for {ticket_id}: {type(e).__name__}: {e}")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
