import argparse
import sys

from scripts.status import CONDITION_STATUSES
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path
from scripts.write_back import write_ticket

EXAMPLE = ('example: python3 -m scripts.mark_condition --ticket VR-0001 --role security '
           '--condition "DPA signed" --status complete')


def usage_error(message):
    print(f"{message}\n{EXAMPLE}", file=sys.stderr)
    return 2


def main(argv):
    parser = argparse.ArgumentParser(
        description="Mark one approval condition pending, complete, or waived.",
    )
    parser.add_argument("--ticket", help="request id, e.g. VR-0001")
    parser.add_argument("--role", help="approver role that set the condition, e.g. security")
    parser.add_argument("--condition", help="condition text, matched exactly")
    parser.add_argument("--status", help="pending, complete, or waived")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the ticket files live in")
    args = parser.parse_args(argv)
    if not args.ticket or not args.role or not args.condition or not args.status:
        return usage_error("--ticket, --role, --condition, and --status are required")
    if args.status not in CONDITION_STATUSES:
        return usage_error(f"--status must be one of {', '.join(CONDITION_STATUSES)}: {args.status!r}")
    if not ticket_path(args.ticket, args.tickets_dir).is_file():
        return usage_error(f"no ticket {args.ticket} in {args.tickets_dir}")

    ticket = read_ticket(args.ticket, args.tickets_dir)
    approver = ticket.get("approvers", {}).get(args.role)
    if approver is None:
        return usage_error(f"{args.ticket}: role {args.role!r} is not on the ticket")
    if args.condition not in (approver.get("conditions") or []):
        return usage_error(f"{args.ticket}: no condition {args.condition!r} on {args.role}")

    approver["condition_status"] = {**(approver.get("condition_status") or {}), args.condition: args.status}
    write_ticket(ticket, args.ticket, args.tickets_dir)
    print(f"{args.ticket}: {args.role} condition marked {args.status}: {args.condition}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
