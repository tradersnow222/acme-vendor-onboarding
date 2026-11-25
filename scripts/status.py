import argparse
import csv
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from scripts.approvals import overall_decision
from scripts.sensitive import checked_text
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
COLUMNS = ["step_id", "step", "actor_type", "actor", "timestamp_pt", "what_they_saw",
           "outcome", "est_cost", "could_be_done_by", "data_label"]
ACTOR_TYPES = ("script", "model", "person")
DATA_LABELS = ("PUBLIC", "SYNTHESIZED", "ASSUMPTION")
CONDITION_STATUSES = ("pending", "complete", "waived")
CONDITION_LEAD_DAYS = 3


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
    checked_text(" ".join(str(value) for value in {**row, "step_id": step_id}.values()))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({**row, "step_id": step_id})


def condition_states(approver):
    stored = approver.get("condition_status") or {}
    return [(text, stored.get(text, "pending")) for text in approver.get("conditions") or []]


def pending_conditions(ticket):
    pending = []
    for approver in ticket.get("approvers", {}).values():
        pending.extend(text for text, status in condition_states(approver) if status == "pending")
    return pending


def condition_warning(ticket, now):
    pending = pending_conditions(ticket)
    raw = ((ticket.get("intake") or {}).get("target_start_date") or {}).get("value")
    if not pending or not raw:
        return None
    try:
        start = date.fromisoformat(str(raw)[:10])
        today = datetime.fromisoformat(now).date()
    except ValueError:
        return None
    if (start - today).days > CONDITION_LEAD_DAYS:
        return None
    return (f"start date {start.isoformat()} is within {CONDITION_LEAD_DAYS} days or past; "
            f"pending conditions: {'; '.join(pending)}")


def build_status(ticket, audit_rows, now):
    approvers = ticket["approvers"]
    final_decision = ticket.get("final_decision")
    verification = ticket.get("verification") or {}
    if final_decision == "withdrawn":
        decision = "withdrawn"
    elif ticket.get("auto_rejected"):
        decision = "rejected"
    elif verification.get("status") == "pending_objection":
        decision = "pending_objection"
    elif verification.get("status") == "approved_auto" and final_decision == "approved":
        decision = "approved"
    else:
        decision = overall_decision(approvers)
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
            role: {
                **{key: a[key] for key in ("name", "decision", "at", "conditions")},
                **({"condition_status": a["condition_status"]} if a.get("condition_status") else {}),
            }
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
    if isinstance(ticket.get("tier"), dict):
        status["tier"] = ticket["tier"].get("tier")
    if ticket.get("auto_rejected"):
        status["auto_rejected"] = True
        status["auto_reject_reasons"] = ", ".join(ticket.get("auto_reject_reasons") or [])
        status["closed_at"] = ticket.get("closed_at")
    if verification.get("status") == "pending_objection":
        status["objection_until"] = verification.get("objection_until")
        status["owner_role"] = verification.get("owner_role")
    if verification.get("status") == "approved_auto":
        status["approved_auto"] = True
    warning = condition_warning(ticket, now)
    if warning:
        status["condition_warning"] = warning
    return status


def format_status(request_id, status):
    lines = [f"{request_id}: {status['decision']}"]
    if status["decision"] == "withdrawn":
        lines.append(f"withdrawn by: {status['withdrawn_by']}")
        lines.append(f"reason: {status['withdrawn_reason']}")
        lines.append(f"closed at: {status['closed_at']}")
    elif status.get("auto_rejected"):
        lines.append(f"auto-rejected: {status.get('auto_reject_reasons')}")
        lines.append(f"tier: {status.get('tier')}")
        lines.append(f"closed at: {status.get('closed_at')}")
    elif status["decision"] == "pending_objection":
        lines.append(f"tier: {status.get('tier')}")
        lines.append(f"objection until: {status.get('objection_until')}")
        lines.append(f"accountable owner: {status.get('owner_role')}")
    else:
        if status.get("tier"):
            lines.append(f"tier: {status['tier']}")
        for role, a in status["approvers"].items():
            line = f"{role}: {a['name'] or '-'}, {a['decision']}, {a['at'] or '-'}"
            if a["conditions"]:
                labeled = [f"{text} ({state})" for text, state in condition_states(a)]
                line += f"; conditions: {'; '.join(labeled)}"
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
    if status.get("condition_warning"):
        lines.append(f"warning: {status['condition_warning']}")
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
