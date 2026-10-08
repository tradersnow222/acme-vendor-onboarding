import sys
from datetime import date

from scripts.intake_check import check_intake
from scripts.samples import load_sample

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


def main(argv):
    if len(argv) != 1:
        print("usage: python3 -m scripts.followup <sample name or request id>", file=sys.stderr)
        return 2
    sample = load_sample(argv[0])
    today = date.fromisoformat(sample["messages"][0]["time"][:10])
    picked = pick_followups(check_intake(sample["expected"]["intake"]["fields"], today), 0)
    asked = "; ".join(f"{q['field']}: {q['question']}" for q in picked["questions"])
    print(f"{sample['request_id']}: follow-up questions: {asked or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
