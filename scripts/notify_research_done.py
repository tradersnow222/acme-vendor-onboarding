#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_SECONDS = 5


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


def send_webhook(ticket_id, status, webhook_url, webhook_secret, webhook_key_header):
    payload = json.dumps({"ticket_id": ticket_id, "status": status}).encode()
    headers = {
        "Content-Type": "application/json",
        webhook_key_header: webhook_secret,
    }
    
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers=headers,
        method="POST",
    )
    
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.status


def main():
    webhook_url = os.environ.get("ACME_WEBHOOK_URL")
    webhook_secret = os.environ.get("ACME_WEBHOOK_SECRET")
    
    if not webhook_url or not webhook_secret:
        sys.exit(0)
    
    webhook_key_header = os.environ.get("ACME_WEBHOOK_KEY_HEADER", "X-Webhook-Key")
    
    hook_input = read_hook_input()
    status = hook_input.get("status", "completed")
    
    ticket_id = find_ticket_id()
    if not ticket_id:
        sys.exit(0)
    
    if check_already_sent(ticket_id):
        sys.exit(0)
    
    try:
        send_webhook(ticket_id, status, webhook_url, webhook_secret, webhook_key_header)
        write_marker(ticket_id)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    
    sys.exit(0)


if __name__ == "__main__":
    main()
