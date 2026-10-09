import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from scripts.check_pack import check_pack
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path

EXAMPLE = "example: python3 -m scripts.write_back --ticket VR-0001 --pack packs/VR-0001/pack.json"


def write_ticket(ticket, request_id, tickets_dir=TICKETS_DIR):
    path = ticket_path(request_id, tickets_dir)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False) as f:
        f.write(json.dumps(ticket, indent=2) + "\n")
    os.replace(f.name, path)


def usage_error(message):
    print(f"{message}\n{EXAMPLE}", file=sys.stderr)
    return 2


def main(argv):
    parser = argparse.ArgumentParser(description="Write a research pack back to its ticket if it passes the pack check.")
    parser.add_argument("--ticket", help="request id, e.g. VR-0001")
    parser.add_argument("--pack", help="path to the pack JSON file")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the tickets live in")
    args = parser.parse_args(argv)
    if not args.ticket or not args.pack:
        return usage_error("both --ticket and --pack are required")
    if not ticket_path(args.ticket, args.tickets_dir).is_file():
        return usage_error(f"no ticket {args.ticket} in {args.tickets_dir}")
    if not Path(args.pack).is_file():
        return usage_error(f"no pack file at {args.pack}")

    ticket = read_ticket(args.ticket, args.tickets_dir)
    pack = json.loads(Path(args.pack).read_text())
    if pack.get("request_id") != ticket["request_id"]:
        print(f"{args.ticket}: pack is for {pack.get('request_id')!r}, not {ticket['request_id']}; ticket not updated")
        return 1

    result = check_pack(pack["rows"])
    if not result["passed"]:
        print(f"{args.ticket}: pack check FAIL")
        for reason in result["reasons"]:
            print(f"- {reason}")
        return 1

    ticket["research"].update(status="done", pack_check=result, pack_path=args.pack)
    ticket["counts"]["exceptions"]["not_found_pack_rows"] = result["not_found"]
    write_ticket(ticket, args.ticket, args.tickets_dir)
    print(f"{args.ticket}: pack check PASS ({len(pack['rows'])} rows, {result['not_found']} not_found); ticket updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
