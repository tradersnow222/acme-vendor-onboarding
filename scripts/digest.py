import argparse
import sys
from datetime import datetime
from pathlib import Path

from scripts.status import ACTOR_TYPES, RUNS_DIR, build_status, read_audit
from scripts.ticket import TICKETS_DIR, read_ticket

EXAMPLE = "example: python3 -m scripts.digest --now 2026-10-09T12:00:00-07:00"
EPILOG = """examples:
  python3 -m scripts.digest
      digest of every open request as of now
  python3 -m scripts.digest --tickets-dir tickets --runs-dir runs --now 2026-10-09T12:00:00-07:00
      same, for given folders and a fixed time"""


def open_tickets(tickets_dir):
    tickets = [read_ticket(path.stem, tickets_dir) for path in sorted(Path(tickets_dir).glob("*.json"))]
    return [t for t in tickets if not t.get("closed_at")]


def format_digest(tickets, runs_dir, now):
    lines = [f"Acme vendor digest {now[:10]}: {len(tickets)} open request(s)"]
    steps = dict.fromkeys(ACTOR_TYPES, 0)
    for ticket in tickets:
        request_id = ticket["request_id"]
        status = build_status(ticket, read_audit(request_id, runs_dir), now)
        waiting = [role for role, a in status["approvers"].items() if a["decision"] == "waiting"]
        lines.append(
            f"{request_id} {ticket['intake']['vendor_legal_name']['value']}: {status['decision']}, "
            f"days open {status['days_open']}, exceptions {status['exceptions']['total']}, "
            f"waiting on {', '.join(waiting) or 'nobody'}"
        )
        for actor_type, n in status["steps_by_actor_type"].items():
            steps[actor_type] += n
    lines.append(f"steps so far: {', '.join(f'{n} {t}' for t, n in steps.items())}")
    return "\n".join(lines)


def main(argv):
    parser = argparse.ArgumentParser(
        description="Print the daily Ops digest of every open vendor request. Prints nothing when none are open.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the ticket files live in")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder the audit logs live in")
    parser.add_argument("--now", default=datetime.now().astimezone().isoformat(timespec="seconds"),
                        help="ISO 8601 time with a UTC offset")
    args = parser.parse_args(argv)
    if datetime.fromisoformat(args.now).tzinfo is None:
        print(f"--now has no UTC offset: {args.now}\n{EXAMPLE}", file=sys.stderr)
        return 2
    tickets = open_tickets(args.tickets_dir)
    if tickets:
        print(format_digest(tickets, args.runs_dir, args.now))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
