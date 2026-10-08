import argparse
import json
from datetime import datetime
from pathlib import Path

from scripts.samples import load_sample

TICKETS_DIR = Path(__file__).resolve().parent.parent / "tickets"


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


def main():
    parser = argparse.ArgumentParser(description="Create the ticket file for a sample request.")
    parser.add_argument("sample", help="sample short name or request id, e.g. zendesk or VR-0001")
    parser.add_argument("--dir", default=TICKETS_DIR, help="folder to write tickets to")
    args = parser.parse_args()
    sample = load_sample(args.sample)
    ticket = create_ticket(sample["request_id"], sample["expected"]["intake"]["fields"], args.dir)
    print(json.dumps(ticket, indent=2))


if __name__ == "__main__":
    main()
