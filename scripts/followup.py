import argparse
import json
import sys
from datetime import date
from pathlib import Path

from scripts.intake_check import check_intake
from scripts.samples import load_sample

EXAMPLE = "example: python3 -m scripts.followup --fields fields.json --today 2026-10-09 --rounds 0"
MAX_ROUNDS = 2
QUESTIONS = {
    "vendor_legal_name": "What is the vendor's legal company name?",
    "website": "What is the vendor's website address?",
    "touches_customer_data": "Will this vendor touch Acme customer data, yes or no?",
    "business_owner": "Who is the business owner? Please give a named person, not a team.",
    "target_start_date": "What date should the vendor start, as YYYY-MM-DD?",
}


def pick_followups(intake_result, rounds_done):
    if intake_result["complete"]:
        return {"questions": [], "exception": False}
    if not intake_result["ask_for"] and not intake_result["confirm"]:
        return {"questions": [], "exception": False}
    if rounds_done >= MAX_ROUNDS:
        return {"questions": [], "exception": True}
    questions = [
        {"field": field, "kind": kind, "question": QUESTIONS[field]}
        for kind, key in (("ask", "ask_for"), ("confirm", "confirm"))
        for field in intake_result[key]
    ]
    return {"questions": questions, "exception": False}


def usage_error(message):
    print(f"{message}\n{EXAMPLE}", file=sys.stderr)
    return 2


def main(argv):
    parser = argparse.ArgumentParser(description="Pick follow-up questions for a sample request or a fields file.")
    parser.add_argument("sample", nargs="?", help="sample short name or request id, e.g. asana or VR-0003")
    parser.add_argument("--fields", help="path to a fields JSON file in the intake-policy.mdc shape")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    parser.add_argument("--rounds", type=int, default=0, help="follow-up rounds already done")
    args = parser.parse_args(argv)
    if args.sample and args.fields:
        return usage_error("give a sample name or --fields, not both")
    if args.fields:
        if not Path(args.fields).is_file():
            return usage_error(f"no fields file at {args.fields}")
        result = check_intake(json.loads(Path(args.fields).read_text()), args.today)
        print(json.dumps({**result, **pick_followups(result, args.rounds)}))
        return 0
    if not args.sample:
        print("usage: python3 -m scripts.followup <sample name or request id>", file=sys.stderr)
        return 2
    sample = load_sample(args.sample)
    today = date.fromisoformat(sample["messages"][0]["time"][:10])
    picked = pick_followups(check_intake(sample["expected"]["intake"]["fields"], today), 0)
    asked = "; ".join(f"{q['field']}: {q['question']}" for q in picked["questions"])
    print(f"{sample['request_id']}: follow-up questions: {asked or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
