import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scripts.samples import load_sample

TICKETS_DIR = Path(__file__).resolve().parent.parent / "tickets"
EXAMPLE = "example: python3 -m scripts.ticket --close VR-0001"
EPILOG = """examples:
  python3 -m scripts.ticket zendesk
      create the ticket for the Zendesk sample and print it
  python3 -m scripts.ticket --close VR-0001 --at 2026-10-09T11:25:00-07:00
      record the final decision once every approver has decided"""


def ticket_path(request_id, tickets_dir=TICKETS_DIR):
    return Path(tickets_dir) / f"{request_id}.json"


def read_ticket(request_id, tickets_dir=TICKETS_DIR):
    return json.loads(ticket_path(request_id, tickets_dir).read_text())


def create_ticket(request_id, fields, tickets_dir=TICKETS_DIR):
    path = ticket_path(request_id, tickets_dir)
    if path.exists():
        return read_ticket(request_id, tickets_dir)
    ticket = {
        "request_id": request_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "intake": fields,
        "research": {"status": None, "pack_check": None},
        "route": [],
        "approvers": {
            "manager": {"name": None, "decision": "waiting", "at": None, "conditions": []},
        },
        "counts": {
            "exceptions": {"missing_intake_fields": 0, "not_found_pack_rows": 0, "rejections": 0},
            "hedged_answers": 0,
            "nudges": 0,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ticket, indent=2) + "\n")
    return ticket


def usage_error(message):
    print(f"{message}\n{EXAMPLE}", file=sys.stderr)
    return 2


def close_ticket(request_id, tickets_dir, runs_dir, at):
    from scripts.approvals import overall_decision
    from scripts.status import RUNS_DIR, append_audit_row
    from scripts.write_back import write_ticket

    ticket = read_ticket(request_id, tickets_dir)
    if ticket.get("closed_at"):
        print(f"{request_id}: already closed {ticket['final_decision']} at {ticket['closed_at']}")
        return 0
    approvers = ticket["approvers"]
    decision = overall_decision(approvers)
    if decision == "waiting":
        waiting = [role for role, approver in approvers.items() if approver["decision"] == "waiting"]
        print(f"{request_id}: cannot close, still waiting on {', '.join(waiting)}")
        return 1

    conditions = [c for approver in approvers.values() for c in approver["conditions"]]
    ticket.update(closed_at=at, final_decision=decision)
    write_ticket(ticket, request_id, tickets_dir)
    outcome = decision + (f"; conditions: {'; '.join(conditions)}" if conditions else "")
    append_audit_row(request_id, {
        "step": "Close-out", "actor_type": "script", "actor": "scripts.ticket", "timestamp_pt": at,
        "outcome": outcome, "est_cost": "~0", "data_label": "SYNTHESIZED",
    }, runs_dir or RUNS_DIR)
    print(f"{request_id}: closed {decision} at {at}")
    if conditions:
        print(f"conditions: {'; '.join(conditions)}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Create the ticket file for a sample request, or close out a decided request.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sample", nargs="?", help="sample short name or request id, e.g. zendesk or VR-0001")
    parser.add_argument("--close", metavar="REQUEST_ID", help="record the final decision on this ticket, e.g. VR-0001")
    parser.add_argument("--dir", default=TICKETS_DIR, help="folder the tickets live in")
    parser.add_argument("--runs-dir", help="folder the audit logs live in (default: runs/)")
    parser.add_argument("--at", default=datetime.now().astimezone().isoformat(timespec="seconds"),
                        help="close-out time, ISO 8601 with a UTC offset (default: now)")
    args = parser.parse_args()
    if bool(args.sample) == bool(args.close):
        return usage_error("give either a sample or --close REQUEST_ID, not both")

    if args.sample:
        sample = load_sample(args.sample)
        ticket = create_ticket(sample["request_id"], sample["expected"]["intake"]["fields"], args.dir)
        print(json.dumps(ticket, indent=2))
        return 0

    if not ticket_path(args.close, args.dir).is_file():
        return usage_error(f"no ticket {args.close} in {args.dir}")
    try:
        has_offset = datetime.fromisoformat(args.at).tzinfo is not None
    except ValueError:
        has_offset = False
    if not has_offset:
        return usage_error(f"--at needs an ISO 8601 time with a UTC offset: {args.at!r}")
    return close_ticket(args.close, args.dir, args.runs_dir, args.at)


if __name__ == "__main__":
    sys.exit(main())
