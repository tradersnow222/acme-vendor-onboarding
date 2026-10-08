import sys
import tempfile
from datetime import date

from scripts.check_pack import check_pack
from scripts.intake_check import check_intake
from scripts.route import format_result, inputs_from_sample, route_request
from scripts.samples import list_samples, load_sample
from scripts.ticket import create_ticket, ticket_path

USAGE = "usage: make run SAMPLE=<zendesk|figma|asana>   e.g. make run SAMPLE=zendesk"
NOT_BUILT = "not built yet"


def step(number, actor, name, outcome):
    print(f"{number}. [{actor}] {name}: {outcome}")


def run(name):
    sample = load_sample(name)
    request_id = sample["request_id"]
    fields = sample["expected"]["intake"]["fields"]

    intake = check_intake(fields, date.fromisoformat(sample["messages"][0]["time"][:10]))
    missing = intake["ask_for"] + intake["confirm"] + intake["fill_from_research"]
    step(1, "script", "Intake check", "complete" if intake["complete"] else f"missing {', '.join(missing)}")

    step(2, "script", "Follow-up questions", NOT_BUILT)

    tickets_dir = tempfile.mkdtemp(prefix="acme-tickets-")
    create_ticket(request_id, fields, tickets_dir)
    step(3, "script", "Ticket", f"wrote {ticket_path(request_id, tickets_dir)}")

    step(4, "model", "Research", NOT_BUILT)

    rows = sample["expected"]["pack"]["rows"]
    if rows is None:
        step(5, "script", "Pack check", NOT_BUILT)
    else:
        pack = check_pack(rows)
        verdict = "PASS" if pack["passed"] else "FAIL"
        step(5, "script", "Pack check", f"{verdict} ({len(rows)} rows, {pack['not_found']} not_found)")

    step(6, "script", "Routing", format_result(request_id, route_request(**inputs_from_sample(sample))))

    step(7, "person", "Approvals", NOT_BUILT)
    step(8, "script", "Status and audit", NOT_BUILT)


def main(argv):
    if len(argv) != 1 or argv[0] not in list_samples():
        print(USAGE, file=sys.stderr)
        return 2
    run(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
