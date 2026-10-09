import argparse
import sys
from datetime import datetime
from pathlib import Path

from scripts.approvals import is_stale, load_config
from scripts.status import RUNS_DIR, append_audit_row
from scripts.ticket import TICKETS_DIR, read_ticket
from scripts.write_back import write_ticket

EXAMPLE = "example: python3 -m scripts.stale_check --now 2026-10-09T10:00:00-07:00"
EPILOG = """examples:
  python3 -m scripts.stale_check
      list approvals that are due a nudge now; prints nothing when none are due
  python3 -m scripts.stale_check --now 2026-10-09T10:00:00-07:00 --record
      same at a fixed time, and record each nudge on the ticket and in the audit log"""


def has_offset(value):
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def due_approvers(ticket, now, config):
    due = []
    for role, approver in ticket["approvers"].items():
        requested_at = approver.get("requested_at")
        nudged_at = approver.get("nudged_at")
        if not requested_at or not is_stale(approver, requested_at, now, config):
            continue
        if nudged_at and not is_stale(approver, nudged_at, now, config):
            continue
        due.append((role, approver))
    return due


def main(argv):
    parser = argparse.ArgumentParser(
        description="List waiting approvals that are due a nudge. Silence is never a yes, so a stale approval only gets a nudge.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the ticket files live in")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder the audit logs live in")
    parser.add_argument("--now", default=datetime.now().astimezone().isoformat(timespec="seconds"),
                        help="current time, ISO 8601 with a UTC offset")
    parser.add_argument("--record", action="store_true", help="record each nudge on the ticket and in the audit log")
    args = parser.parse_args(argv)
    if not has_offset(args.now):
        print(f"--now needs a UTC offset: {args.now!r}\n{EXAMPLE}", file=sys.stderr)
        return 2

    config = load_config()
    now = datetime.fromisoformat(args.now)
    for path in sorted(Path(args.tickets_dir).glob("*.json")):
        request_id = path.stem
        ticket = read_ticket(request_id, args.tickets_dir)
        if ticket.get("closed_at"):
            continue
        for role, approver in due_approvers(ticket, args.now, config):
            hours = (now - datetime.fromisoformat(approver["requested_at"])).total_seconds() / 3600
            print(f"{request_id}: {role} has waited {round(hours, 1)} hours since {approver['requested_at']}; nudge due")
            if not args.record:
                continue
            approver["nudged_at"] = args.now
            ticket["counts"]["nudges"] += 1
            write_ticket(ticket, request_id, args.tickets_dir)
            append_audit_row(request_id, {
                "step": "Stale-approval nudge",
                "actor_type": "script",
                "actor": "scripts.stale_check",
                "timestamp_pt": args.now,
                "outcome": f"nudge due for {role}; silence is not a yes",
                "est_cost": "~0",
                "data_label": "SYNTHESIZED",
            }, args.runs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
