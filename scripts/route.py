import sys

from scripts.samples import load_sample


def route_request(intake_fields, r3_shows_customer_data, intake_passed, pack_passed):
    blocked_reasons = []
    if not intake_passed:
        blocked_reasons.append("intake check has not passed")
    if not pack_passed:
        blocked_reasons.append("pack check has not passed")
    if blocked_reasons:
        return {"route": [], "blocked": True, "blocked_reasons": blocked_reasons, "mismatch": False}

    intake_says = intake_fields["touches_customer_data"]["value"] is True
    mismatch = r3_shows_customer_data is not None and intake_says != r3_shows_customer_data
    route = ["manager"]
    if intake_says or r3_shows_customer_data:
        route.append("security")
    return {"route": route, "blocked": False, "blocked_reasons": [], "mismatch": mismatch}


def inputs_from_sample(sample):
    expected = sample["expected"]
    pack = expected["pack"]
    if "check" in pack:
        r3 = pack["check"]["r3_shows_personal_data"]
    else:
        r3 = pack.get("r3_should_show_acme_customer_data")
    gates = expected["routing"]["gate_checks"]
    return {
        "intake_fields": expected["intake"]["fields"],
        "r3_shows_customer_data": r3,
        "intake_passed": gates["intake_complete"],
        "pack_passed": gates["pack_complete"],
    }


def format_result(request_id, result):
    lines = [f"{request_id}: route = {', '.join(result['route']) or 'none'}"]
    if result["blocked"]:
        lines.append(f"blocked: {'; '.join(result['blocked_reasons'])}")
    if result["mismatch"]:
        lines.append("mismatch: intake and pack R3 disagree on customer data; routed to Security")
    return "\n".join(lines)


def main(argv):
    if len(argv) != 1:
        print("usage: python3 -m scripts.route <sample name or request id>", file=sys.stderr)
        return 2
    sample = load_sample(argv[0])
    print(format_result(sample["request_id"], route_request(**inputs_from_sample(sample))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
