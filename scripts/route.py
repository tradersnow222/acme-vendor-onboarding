import sys

from scripts.approvals import load_config
from scripts.samples import load_sample


def _rule(config):
    return config.get("data_sensitivity") or {}


def r3_from_pack(pack, config=None):
    rule = _rule(config or load_config())
    if "check" in pack:
        return pack["check"].get(rule.get("pack_check_flag", "r3_shows_personal_data"))
    for key in rule.get("legacy_pack_flags") or []:
        if key in pack:
            return pack[key]
    return None


def route_request(intake_fields, r3_shows_customer_data, intake_passed, pack_passed, config=None):
    config = config or load_config()
    blocked_reasons = []
    if not intake_passed:
        blocked_reasons.append("intake check has not passed")
    if not pack_passed:
        blocked_reasons.append("pack check has not passed")
    if blocked_reasons:
        return {"route": [], "blocked": True, "blocked_reasons": blocked_reasons, "mismatch": False}

    rule = _rule(config)
    field = rule.get("intake_field", "touches_customer_data")
    security_role = rule.get("security_role", "security")
    intake_says = intake_fields[field]["value"] is True
    mismatch = r3_shows_customer_data is not None and intake_says != r3_shows_customer_data
    route = list(config.get("always_route") or ["manager"])
    if (intake_says or r3_shows_customer_data) and security_role not in route:
        route.append(security_role)
    return {"route": route, "blocked": False, "blocked_reasons": [], "mismatch": mismatch}


def inputs_from_sample(sample, config=None):
    expected = sample["expected"]
    gates = expected["routing"]["gate_checks"]
    return {
        "intake_fields": expected["intake"]["fields"],
        "r3_shows_customer_data": r3_from_pack(expected["pack"], config),
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
