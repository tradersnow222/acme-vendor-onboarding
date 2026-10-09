import argparse
import sys
from datetime import datetime

from scripts.approvals import overall_decision, record_decision
from scripts.status import RUNS_DIR, append_audit_row
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path
from scripts.write_back import write_ticket

EXAMPLE = ('example: python3 -m scripts.record_approval --ticket VR-0001 --role manager '
           '--name "Daniel Okafor [SYNTHESIZED]" --decision approved --quote "Fine for 90 days."')
EPILOG = """examples:
  python3 -m scripts.record_approval --ticket VR-0001 --role manager --name "Daniel Okafor [SYNTHESIZED]" \\
      --decision approved --quote "Fine for 90 days on Suite Professional monthly, cap 8 seats."
  python3 -m scripts.record_approval --ticket VR-0001 --role security --name "Lena Hoffmann [SYNTHESIZED]" \\
      --decision approved_with_conditions --quote "approved" --condition "DPA signed" \\
      --condition "SSO via SAML required for all agents" --at 2026-10-09T11:25:00-07:00"""


def usage_error(message):
    print(f"{message}\n{EXAMPLE}", file=sys.stderr)
    return 2


def has_offset(text):
    try:
        return datetime.fromisoformat(text).tzinfo is not None
    except ValueError:
        return False


def main(argv):
    parser = argparse.ArgumentParser(
        description="Record a decision a named approver already gave, on the ticket and in the audit log.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ticket", help="request id of the ticket, e.g. VR-0001")
    parser.add_argument("--role", help="approver role in the route, e.g. manager or security")
    parser.add_argument("--name", help="the approver's name as they gave it")
    parser.add_argument("--decision", help="approved, approved_with_conditions or rejected")
    parser.add_argument("--quote", help="the approver's exact words")
    parser.add_argument("--condition", action="append", default=[], help="a condition; repeat for each one")
    parser.add_argument("--at", default=datetime.now().astimezone().isoformat(timespec="seconds"),
                        help="when the decision was given, ISO 8601 with UTC offset")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the ticket files live in")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder the audit logs live in")
    args = parser.parse_args(argv)

    if not args.ticket:
        return usage_error("--ticket is required")
    if not args.quote:
        return usage_error("--quote is required")
    if not has_offset(args.at):
        return usage_error(f"--at needs a UTC offset: {args.at}")
    if not ticket_path(args.ticket, args.tickets_dir).is_file():
        return usage_error(f"no ticket {args.ticket} in {args.tickets_dir}")

    ticket = read_ticket(args.ticket, args.tickets_dir)
    try:
        updated = record_decision(ticket["approvers"], args.role, args.name, args.decision, args.at, args.condition)
    except ValueError as error:
        print(f"{args.ticket}: not recorded: {error}")
        return 1

    ticket["approvers"][args.role] = {**ticket["approvers"][args.role], **updated[args.role]}
    write_ticket(ticket, args.ticket, args.tickets_dir)
    outcome = f'{args.decision}: "{args.quote}"'
    if args.condition:
        outcome += f"; conditions: {'; '.join(args.condition)}"
    append_audit_row(args.ticket, {
        "step": "Approval", "actor_type": "person", "actor": args.name, "timestamp_pt": args.at,
        "what_they_saw": "pack summary and status", "outcome": outcome, "est_cost": "~0", "data_label": "SYNTHESIZED",
    }, args.runs_dir)
    overall = overall_decision(ticket["approvers"])
    print(f"{args.ticket}: recorded {args.role} {args.name} {args.decision}; overall {overall}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
