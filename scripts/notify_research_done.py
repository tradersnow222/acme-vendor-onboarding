#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from scripts.status import RUNS_DIR, append_audit_row
from scripts.ticket import TICKETS_DIR

MARKER_FILE = ".webhook_sent"
TIMEOUT_SECONDS = 5


def read_stdin_context():
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def get_ticket_id_from_context(context):
    return context.get("ticket_id")


def get_ticket_id_from_branch():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            match = re.search(r"VR-\d{4}", branch)
            return match.group(0) if match else None
    except Exception:
        pass
    return None


def get_ticket_id_from_tickets_dir():
    tickets_dir_path = os.environ.get("TICKETS_DIR", TICKETS_DIR)
    tickets_dir = Path(tickets_dir_path)
    if not tickets_dir.exists():
        return None
    
    for ticket_file in sorted(tickets_dir.glob("VR-*.json"), reverse=True):
        try:
            ticket = json.loads(ticket_file.read_text())
            research = ticket.get("research", {})
            if research.get("agent_id") and not research.get("status"):
                return ticket["request_id"]
        except Exception:
            continue
    return None


def get_ticket_id(context):
    ticket_id = get_ticket_id_from_context(context)
    if ticket_id:
        return ticket_id
    
    ticket_id = get_ticket_id_from_branch()
    if ticket_id:
        return ticket_id
    
    return get_ticket_id_from_tickets_dir()


def get_status_from_context(context):
    return context.get("status", "completed")


def check_marker_exists(ticket_id, runs_dir):
    marker_path = Path(runs_dir) / ticket_id / MARKER_FILE
    return marker_path.exists()


def write_marker(ticket_id, runs_dir):
    marker_path = Path(runs_dir) / ticket_id / MARKER_FILE
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(datetime.now().astimezone().isoformat(timespec="seconds") + "\n")


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
    
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "timeout or network error"


def log_audit(ticket_id, status, outcome, runs_dir):
    try:
        append_audit_row(ticket_id, {
            "step": "Research webhook",
            "actor_type": "script",
            "actor": "scripts.notify_research_done",
            "timestamp_pt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "outcome": outcome,
            "est_cost": "~0",
            "data_label": "PUBLIC",
        }, runs_dir)
    except Exception:
        pass


def main():
    webhook_url = os.environ.get("ACME_WEBHOOK_URL")
    webhook_secret = os.environ.get("ACME_WEBHOOK_SECRET")
    webhook_key_header = os.environ.get("ACME_WEBHOOK_KEY_HEADER", "X-Webhook-Key")
    
    if not webhook_url or not webhook_secret:
        sys.exit(0)
    
    context = read_stdin_context()
    
    ticket_id = get_ticket_id(context)
    if not ticket_id:
        sys.exit(0)
    
    runs_dir = os.environ.get("RUNS_DIR", RUNS_DIR)
    
    if check_marker_exists(ticket_id, runs_dir):
        sys.exit(0)
    
    status = get_status_from_context(context)
    write_marker(ticket_id, runs_dir)
    
    http_status, response = send_webhook(ticket_id, status, webhook_url, webhook_secret, webhook_key_header)
    
    if http_status:
        outcome = f"webhook sent: {ticket_id} {status}, HTTP {http_status}"
    else:
        outcome = f"webhook failed: {ticket_id} {status}, {response}"
    
    log_audit(ticket_id, status, outcome, runs_dir)
    sys.exit(0)


if __name__ == "__main__":
    main()
