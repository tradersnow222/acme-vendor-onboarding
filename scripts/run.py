import sys
import tempfile
from datetime import date, datetime

from scripts.approvals import record_decision
from scripts.check_pack import check_pack
from scripts.followup import pick_followups
from scripts.intake_check import check_intake
from scripts.launch_research import build_body
from scripts.route import format_result, inputs_from_sample, route_request
from scripts.samples import list_samples, load_sample, sample_fetch_log
from scripts.status import ACTOR_TYPES, append_audit_row, audit_path, build_status, read_audit
from scripts.ticket import create_ticket, ticket_path
from scripts.write_back import write_ticket

USAGE = "usage: make run SAMPLE=<zendesk|figma|asana>   e.g. make run SAMPLE=zendesk"
NOT_BUILT = "not built yet"
STEP_ACTORS = {
    1: "scripts.intake_check",
    2: "scripts.followup",
    3: "scripts.ticket",
    4: "Cursor cloud agent (dry run)",
    5: "scripts.check_pack",
    6: "scripts.route",
}


def step(number, actor, name, outcome, steps):
    steps.append((number, actor, name, outcome))
    print(f"{number}. [{actor}] {name}: {outcome}")


def run(name):
    sample = load_sample(name)
    request_id = sample["request_id"]
    intake_expected = sample["expected"]["intake"]
    fields = intake_expected["fields"]
    steps = []

    intake = check_intake(fields, date.fromisoformat(sample["messages"][0]["time"][:10]))
    missing = intake["ask_for"] + intake["confirm"] + intake["fill_from_research"]
    step(1, "script", "Intake check", "complete" if intake["complete"] else f"missing {', '.join(missing)}", steps)

    first = intake_expected["after_first_message"]
    questions = pick_followups({**first, "complete": not any(first.values())}, 0)["questions"]
    asked = ", ".join(q["field"] for q in questions)
    rounds = intake_expected["rounds_used"]
    step(2, "script", "Follow-up questions",
         f"round 1 asked {asked}; complete after {rounds} round(s)" if questions else "none needed", steps)

    tickets_dir = tempfile.mkdtemp(prefix="acme-tickets-")
    ticket = create_ticket(request_id, fields, tickets_dir)
    ticket["created_at"] = sample["messages"][0]["time"]
    ticket["counts"]["exceptions"]["missing_intake_fields"] = len(first["ask_for"])
    step(3, "script", "Ticket", f"wrote {ticket_path(request_id, tickets_dir)}", steps)

    build_body(ticket)
    step(4, "model", "Research",
         f"dry run, nothing sent; live: python3 -m scripts.launch_research --ticket {request_id} --live", steps)

    rows = sample["expected"]["pack"]["rows"]
    if rows is None:
        step(5, "script", "Pack check", NOT_BUILT, steps)
    else:
        pack = check_pack(rows, sample_fetch_log(request_id))
        ticket["counts"]["exceptions"]["not_found_pack_rows"] = pack["not_found"]
        verdict = "PASS" if pack["passed"] else "FAIL"
        step(5, "script", "Pack check", f"{verdict} ({len(rows)} rows, {pack['not_found']} not_found)", steps)

    routed = route_request(**inputs_from_sample(sample))
    step(6, "script", "Routing", format_result(request_id, routed), steps)

    for role in routed["route"]:
        ticket["approvers"].setdefault(role, {"name": None, "decision": "waiting", "at": None, "conditions": []})
    for reply in sample["approver_replies"]:
        ticket["approvers"] = record_decision(
            ticket["approvers"], reply["role"], reply["approver"], reply["decision"], reply["time"], reply["conditions"]
        )
    ticket["closed_at"] = sample["expected"]["status"]["decided_at"]
    write_ticket(ticket, request_id, tickets_dir)
    step(7, "person", "Approvals",
         "; ".join(f"{role} {a['name']} {a['decision']}" for role, a in ticket["approvers"].items()), steps)

    runs_dir = tempfile.mkdtemp(prefix="acme-runs-")
    last_message_time = sample["messages"][-1]["time"]
    append_audit_row(request_id, {
        "step": "Request received", "actor_type": "person", "actor": sample["people"]["requester"]["name"],
        "timestamp_pt": sample["messages"][0]["time"], "data_label": "SYNTHESIZED",
    }, runs_dir)
    for number, actor_type, step_name, outcome in steps[:6]:
        append_audit_row(request_id, {
            "step": step_name, "actor_type": actor_type, "actor": STEP_ACTORS[number],
            "timestamp_pt": last_message_time, "outcome": outcome,
            "est_cost": "0 tokens (dry run)" if actor_type == "model" else "~0", "data_label": "SYNTHESIZED",
        }, runs_dir)
    for reply in sample["approver_replies"]:
        append_audit_row(request_id, {
            "step": "Approval", "actor_type": "person", "actor": reply["approver"],
            "timestamp_pt": reply["time"], "outcome": reply["decision"], "data_label": "SYNTHESIZED",
        }, runs_dir)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    status = build_status(ticket, read_audit(request_id, runs_dir), now)
    counts = ", ".join(f"{status['steps_by_actor_type'].get(t, 0)} {t}" for t in ACTOR_TYPES)
    print(f"8. [script] Status and audit: {status['decision']}, days open {status['days_open']}, "
          f"exceptions {status['exceptions']['total']}, steps {counts}; audit {audit_path(request_id, runs_dir)}")


def main(argv):
    if len(argv) != 1 or argv[0] not in list_samples():
        print(USAGE, file=sys.stderr)
        return 2
    run(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
