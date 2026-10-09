import argparse
import sys
from datetime import date, datetime

from scripts.intake_check import check_intake
from scripts.route import route_request
from scripts.status import RUNS_DIR, append_audit_row
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path
from scripts.write_back import write_ticket

EXAMPLE = "example: python3 -m scripts.request_approvals --ticket VR-0001 --at 2026-10-08T09:36:00-07:00"
EPILOG = """examples:
  python3 -m scripts.request_approvals --ticket VR-0001
      route the ticket and record that each approval request went out now
  python3 -m scripts.request_approvals --ticket VR-0001 --at 2026-10-08T09:36:00-07:00 --today 2026-10-08
      same, with a fixed send time and intake check date"""


def usage_error(message):
    print(f"{message}\n{EXAMPLE}", file=sys.stderr)
    return 2


def request_approvals(ticket, at, today):
    intake_passed = check_intake(ticket["intake"], today)["complete"]
    pack_passed = ticket["research"].get("status") == "done"
    result = route_request(ticket["intake"], None, intake_passed, pack_passed)
    if result["blocked"]:
        return result, []
    ticket["route"] = result["route"]
    requested = []
    for role in result["route"]:
        entry = ticket["approvers"].setdefault(
            role, {"name": None, "decision": "waiting", "at": None, "conditions": []})
        if entry["decision"] == "waiting" and not entry.get("requested_at"):
            entry["requested_at"] = at
            requested.append(role)
    return result, requested


def main(argv):
    parser = argparse.ArgumentParser(
        description="Route a ticket to its approvers and record when each approval request went out.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ticket", help="request id of the ticket, e.g. VR-0001")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the ticket files live in")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder the audit logs live in")
    parser.add_argument("--at", default=datetime.now().astimezone().isoformat(timespec="seconds"),
                        help="when the requests went out, ISO 8601 with a UTC offset (default: now)")
    parser.add_argument("--today", type=date.fromisoformat,
                        help="date for the intake check, YYYY-MM-DD (default: the date part of --at)")
    args = parser.parse_args(argv)

    if not args.ticket:
        return usage_error("--ticket is required")
    if not ticket_path(args.ticket, args.tickets_dir).is_file():
        return usage_error(f"no ticket {args.ticket} in {args.tickets_dir}")
    try:
        at_time = datetime.fromisoformat(args.at)
    except ValueError:
        at_time = None
    if at_time is None or at_time.tzinfo is None:
        return usage_error(f"--at needs ISO 8601 with a UTC offset: {args.at!r}")

    ticket = read_ticket(args.ticket, args.tickets_dir)
    result, requested = request_approvals(ticket, args.at, args.today or at_time.date())
    if result["blocked"]:
        print(f"{args.ticket}: blocked: {'; '.join(result['blocked_reasons'])}")
        return 1
    if not requested:
        times = ", ".join(f"{role} {ticket['approvers'][role].get('requested_at') or '-'}" for role in result["route"])
        print(f"{args.ticket}: approvals already requested: {times}")
        return 0

    write_ticket(ticket, args.ticket, args.tickets_dir)
    for role in requested:
        append_audit_row(args.ticket, {
            "step": "Approval requested",
            "actor_type": "script",
            "actor": "scripts.request_approvals",
            "timestamp_pt": args.at,
            "outcome": f"{role} asked",
            "est_cost": "~0",
            "data_label": "SYNTHESIZED",
        }, args.runs_dir)
    print(f"{args.ticket}: approval requested from {', '.join(requested)} at {args.at}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
