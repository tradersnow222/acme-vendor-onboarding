import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from scripts.approvals import overall_decision
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
COLUMNS = ["step_id", "step", "actor_type", "actor", "timestamp_pt", "what_they_saw",
           "outcome", "est_cost", "could_be_done_by", "data_label"]
ACTOR_TYPES = ("script", "model", "person")
DATA_LABELS = ("PUBLIC", "SYNTHESIZED", "ASSUMPTION")


def audit_path(request_id, runs_dir=RUNS_DIR):
    return Path(runs_dir) / request_id / "audit.csv"


def read_audit(request_id, runs_dir=RUNS_DIR):
    path = audit_path(request_id, runs_dir)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append_audit_row(request_id, row, runs_dir=RUNS_DIR):
    if row.get("actor_type") not in ACTOR_TYPES:
        raise ValueError(f"actor_type must be one of {ACTOR_TYPES}: {row.get('actor_type')!r}")
    if not (row.get("actor") or "").strip():
        raise ValueError("actor is blank")
    if datetime.fromisoformat(row.get("timestamp_pt") or "").tzinfo is None:
        raise ValueError(f"timestamp_pt has no UTC offset: {row['timestamp_pt']!r}")
    if row.get("data_label") not in DATA_LABELS:
        raise ValueError(f"data_label must be one of {DATA_LABELS}: {row.get('data_label')!r}")
    path = audit_path(request_id, runs_dir)
    is_new = not path.exists()
    step_id = len(read_audit(request_id, runs_dir)) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({**row, "step_id": step_id})


def build_status(ticket, audit_rows, now):
    approvers = ticket["approvers"]
    final_decision = ticket.get("final_decision")
    decision = final_decision if final_decision == "withdrawn" else overall_decision(approvers)
    opened = datetime.fromisoformat(ticket.get("created_at") or audit_rows[0]["timestamp_pt"])
    end = datetime.fromisoformat(ticket.get("closed_at") or now)
    days_open = round((end - opened).total_seconds() / 86400, 1)
    counts = ticket["counts"]
    exceptions = {
        "missing_intake_fields": counts["exceptions"]["missing_intake_fields"],
        "not_found_pack_rows": counts["exceptions"]["not_found_pack_rows"],
        "rejections": sum(a["decision"] == "rejected" for a in approvers.values()),
    }
    exceptions["total"] = sum(exceptions.values())
    status = {
        "decision": decision,
        "approvers": {
            role: {key: a[key] for key in ("name", "decision", "at", "conditions")}
            for role, a in approvers.items()
        },
        "days_open": days_open,
        "exceptions": exceptions,
        "hedged_answers": counts["hedged_answers"],
        "nudges": counts["nudges"],
        "steps_by_actor_type": dict(Counter(row["actor_type"] for row in audit_rows)),
    }
    if decision == "withdrawn":
        status["withdrawn_by"] = ticket.get("withdrawn_by")
        status["withdrawn_reason"] = ticket.get("withdrawn_reason")
        status["closed_at"] = ticket.get("closed_at")
    return status


def format_status(request_id, status):
    lines = [f"{request_id}: {status['decision']}"]
    if status["decision"] == "withdrawn":
        lines.append(f"withdrawn by: {status['withdrawn_by']}")
        lines.append(f"reason: {status['withdrawn_reason']}")
        lines.append(f"closed at: {status['closed_at']}")
    else:
        for role, a in status["approvers"].items():
            line = f"{role}: {a['name'] or '-'}, {a['decision']}, {a['at'] or '-'}"
            if a["conditions"]:
                line += f"; conditions: {'; '.join(a['conditions'])}"
            lines.append(line)
    ex = status["exceptions"]
    steps = status["steps_by_actor_type"]
    lines += [
        f"days open: {status['days_open']}",
        f"exceptions: {ex['total']} (missing intake fields {ex['missing_intake_fields']}, "
        f"not found pack rows {ex['not_found_pack_rows']}, rejections {ex['rejections']})",
        f"hedged answers: {status['hedged_answers']}, nudges: {status['nudges']}",
        f"steps: {', '.join(f'{steps.get(t, 0)} {t}' for t in ACTOR_TYPES)}",
    ]
    return "\n".join(lines)


def main(argv):
    parser = argparse.ArgumentParser(description="Print the status of one vendor request.")
    parser.add_argument("--ticket", required=True, help="request id, e.g. VR-0001")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR)
    parser.add_argument("--runs-dir", default=RUNS_DIR)
    parser.add_argument("--now", default=datetime.now().astimezone().isoformat(timespec="seconds"))
    args = parser.parse_args(argv)
    if not ticket_path(args.ticket, args.tickets_dir).exists():
        print(f"no ticket found: {args.ticket}   e.g. python3 -m scripts.status --ticket VR-0001", file=sys.stderr)
        return 2
    ticket = read_ticket(args.ticket, args.tickets_dir)
    status = build_status(ticket, read_audit(args.ticket, args.runs_dir), args.now)
    print(format_status(args.ticket, status))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
