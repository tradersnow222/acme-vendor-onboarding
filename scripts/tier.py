"""A tiering policy the company sets.

Inherent risk is the tier. It only chooses the route. Residual risk is the
named person's accept, reject, or conditions, recorded later. A SOC 2 report
does not drop the tier. The script never treats silence as a yes.

The 11 questions below are factual. Nothing asks the requester to name a tier.
The sanctions screen reads the company lists in config. It does not use the network.

Applied rules: approval-policy.mdc, status-and-audit.mdc, data-boundaries.mdc.
"""

import copy
import hashlib
import re

from scripts.approvals import load_config

TIERS = ("low", "medium", "high")
QUESTIONS = (
    ("q1_purpose", "What will this vendor do for us?"),
    ("q2_handles_data", "Will the vendor create, receive, store, process, or transmit our company data or our customers' data? (Yes / No / Unsure)"),
    ("q3_data_types", "If not No, which data types apply? Public, internal business, employee personal data, customer personal data, PHI, PCI, or other regulated."),
    ("q4_ai_training", "Will the vendor use our company or customer data to train, fine-tune, or improve an AI model? (Yes / No / Unsure)"),
    ("q5_sso_or_oauth", "Will anyone sign in with company SSO, OAuth, or another company identity provider? (Yes / No / Unsure)"),
    ("q6_access", "What system access is required? None, read-only, write or API, or privileged (production or admin)."),
    ("q7_critical_impact", "If this vendor failed, would it significantly harm customers, revenue, or core operations? (Yes / No / Unsure)"),
    ("q8_spend", "Estimated annual contract value, as a number or Unsure."),
    ("q9_countries", "Country of legal organization, and every country where our data will be stored or processed. A list, or Unsure."),
    ("q10_subprocessors", "Will any subprocessor have access to our data or systems? (Yes / No / Unsure)"),
    ("q11_budget_owner", "Who is the named business owner, and who is the named budget owner?"),
)
BLANK_KEYS = (
    "q2_handles_data", "q3_data_types", "q4_ai_training", "q5_sso_or_oauth", "q6_access",
    "q7_critical_impact", "q8_spend", "q9_countries", "q10_subprocessors",
)
HIGH_GAP = {"q3_data_types", "q4_ai_training", "q6_access", "q9_countries"}
YES_WORDS = {"yes", "y", "true"}
NO_WORDS = {"no", "n", "false"}
TRIGGER_ORDER = (
    "phi_pci_or_regulated", "privileged_access", "ai_training", "critical_impact",
    "customer_or_employee_pii", "sso_oauth_or_write_api", "spend_threshold",
    "subprocessors", "unapproved_geography",
)

DEFAULT_TIERING = {
    "auto_decide": False,
    "objection_hours": 24,
    "fast_lane_hours": None,
    "spend_threshold": 10000,
    "low_sample_percent": 10,
    "auto_sample_percent": 10,
    "max_verify_rounds": 3,
    "required_docs": ["oauth_scopes", "privacy_policy"],
    "target_days": {"low": 2, "medium": 10, "high": 15},
    "escalate_to": "security",
    "sanctions_reviewer": "security",
    "verifiers": ["rules", "docs"],
    "uncertain_answers": ["not sure", "unsure", "unknown", "n/a", "na", "tbd", "idk"],
    "location_refusal_answers": ["refuse", "refused", "will not say", "declined"],
    "call_recording_phrases": ["records calls", "call recording", "records the call"],
    "sensitive_oauth_markers": ["drive", "gmail", "calendar", "mail.google"],
    "privacy_data_phrases": ["records calls", "call recording", "records the call", "personal data", "customer data"],
    "sanctioned_countries": ["CU", "Cuba", "IR", "Iran", "KP", "North Korea", "SY", "Syria"],
    "confirmed_parties": ["Blocked Example Party"],
    "potential_parties": ["Potential Example Match"],
    "banned_categories": ["spyware", "stalkerware", "cryptocurrency mixer"],
    "approved_countries": ["US", "USA", "United States", "CA", "Canada", "GB", "UK", "United Kingdom",
                           "AU", "Australia", "DE", "Germany", "FR", "France", "IE", "Ireland",
                           "NL", "Netherlands", "SE", "Sweden", "JP", "Japan", "SG", "Singapore", "NZ", "New Zealand"],
    "routes": {
        "low": ["manager"],
        "medium": ["manager", "security"],
        "high": ["manager", "security", "legal", "privacy"],
    },
    "extra_approvers": {
        "customer_or_employee_pii": ["privacy"],
        "sso_oauth_or_write_api": ["legal"],
        "spend_threshold": ["finance"],
        "critical_impact": ["executive"],
    },
    "triggers": {
        "phi_pci_or_regulated": {"tier": "high", "enabled": True},
        "privileged_access": {"tier": "high", "enabled": True},
        "ai_training": {"tier": "high", "enabled": True},
        "critical_impact": {"tier": "high", "enabled": True},
        "customer_or_employee_pii": {"tier": "medium", "enabled": True},
        "sso_oauth_or_write_api": {"tier": "medium", "enabled": True},
        "spend_threshold": {"tier": "medium", "enabled": True},
        "subprocessors": {"tier": "medium", "enabled": True},
        "unapproved_geography": {"tier": "medium", "enabled": True},
    },
    "score": {
        "data_public_or_none": 0,
        "data_internal_only": 2,
        "access_none": 0,
        "criticality_no": 0,
        "subprocessors_no_access": 0,
        "low_max": 2,
        "medium_max": 5,
    },
}


def merged_tiering(config=None):
    config = config or load_config()
    base = copy.deepcopy(DEFAULT_TIERING)
    raw = config.get("tiering")
    if not isinstance(raw, dict):
        return base
    for key, value in raw.items():
        if key == "triggers" and isinstance(value, dict):
            for name, spec in value.items():
                if isinstance(spec, dict) and isinstance(base["triggers"].get(name), dict):
                    base["triggers"][name] = {**base["triggers"][name], **spec}
                else:
                    base["triggers"][name] = spec
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    if base.get("fast_lane_hours") is None:
        base["fast_lane_hours"] = config.get("stale_after_hours", 20)
    return base


def fast_lane_hours(config=None):
    config = config or load_config()
    return merged_tiering(config)["fast_lane_hours"]


def trigger_floor(policy, name):
    spec = (policy.get("triggers") or {}).get(name) or {}
    if isinstance(spec, dict) and spec.get("enabled") is False:
        return None
    default = "high" if name in TRIGGER_ORDER[:4] else "medium"
    floor = spec.get("tier", default) if isinstance(spec, dict) else default
    return floor if floor in ("medium", "high") else default


def norm_answer(value):
    return str(value if value is not None else "").strip().casefold().strip(" ?.!")


def answer_kind(value, uncertain):
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = norm_answer(value)
    if text == "" or text in uncertain:
        return "blank"
    if text in NO_WORDS:
        return "no"
    if text in YES_WORDS:
        return "yes"
    return "other"


def is_blank(value, uncertain):
    return answer_kind(value, uncertain) == "blank"


def split_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = re.split(r"[;,/|]", str(value))
    return [str(part).strip() for part in parts if str(part).strip()]


def phrase_hit(text, phrases):
    lowered = str(text or "").casefold()
    for phrase in phrases or []:
        needle = str(phrase).casefold()
        if not needle or needle not in lowered:
            continue
        if any(skip in lowered for skip in (f"no {needle}", f"not {needle}", f"without {needle}")):
            continue
        return True
    return False


def norm_name(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())


def same_person(left, right):
    def simplify(value):
        text = str(value or "").casefold().replace("[synthesized]", "")
        return " ".join(text.split(",")[0].split())
    a, b = simplify(left), simplify(right)
    return bool(a) and a == b


def country_in(country, names):
    token = str(country).strip()
    if not token:
        return False
    folded = {norm_name(name) for name in names}
    upper = {str(name).strip().upper() for name in names}
    if len(token) <= 3 and token.upper() in upper:
        return True
    return norm_name(token) in folded


def parse_spend(value, uncertain):
    if is_blank(value, uncertain):
        return "blank"
    if isinstance(value, bool):
        return "blank"
    if isinstance(value, (int, float)):
        return float(value)
    text = norm_answer(value).replace("$", "").replace(",", "")
    if text in {"free", "none", "no", "0"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return "blank"


def parse_access(value, uncertain):
    kind = answer_kind(value, uncertain)
    if kind == "blank":
        return "blank"
    text = norm_answer(value)
    if text in NO_WORDS or text in {"none", "no access"}:
        return "none"
    if any(word in text for word in ("privileg", "admin", "production", "prod")):
        return "privileged"
    if "write" in text or "api" in text:
        return "write_or_api"
    if "read" in text or "standalone" in text:
        return "read_only"
    return "write_or_api"


def data_kinds(value):
    kinds = set()
    for part in split_list(value):
        token = norm_name(part)
        words = set(token.split())
        if "phi" in words or "health" in token or token in {"phi", "protected health information"}:
            kinds.add("phi")
        elif "pci" in words or "payment card" in token or token == "cardholder data":
            kinds.add("pci")
        elif "regulated" in token:
            kinds.add("regulated")
        elif "pii" in words or ("employee" in token and "personal" in token) or ("customer" in token and "personal" in token):
            kinds.add("pii")
        elif token in {"internal", "internal business", "internal business information"} or token.startswith("internal "):
            kinds.add("internal")
        elif token in {"public", "publicly available", "publicly available information", "none"}:
            kinds.add("public")
        elif token:
            kinds.add("pii")
    return kinds


def screen_sanctions(names, countries, policy):
    confirmed, potential = [], []
    confirmed_names = {norm_name(name) for name in policy.get("confirmed_parties") or []}
    potential_names = {norm_name(name) for name in policy.get("potential_parties") or []}
    for name in names:
        folded = norm_name(name)
        if not folded:
            continue
        if folded in confirmed_names:
            confirmed.append(name)
        elif folded in potential_names:
            potential.append(name)
    for country in countries:
        if country_in(country, policy.get("sanctioned_countries") or []):
            confirmed.append(str(country))
    status = "confirmed" if confirmed else "potential" if potential else "clear"
    return {"status": status, "matches": confirmed + potential}


def _names(scope, vendor_name):
    names = [vendor_name] if vendor_name else []
    names.extend(split_list(scope.get("aliases")))
    names.extend(split_list(scope.get("owners")))
    return names


def at_least(tier, floor):
    return TIERS[max(TIERS.index(tier), TIERS.index(floor))]


def tier_from_score(score, policy):
    low_max = policy["score"].get("low_max", 2)
    medium_max = policy["score"].get("medium_max", 5)
    if score <= low_max:
        return "low"
    if score <= medium_max:
        return "medium"
    return "high"


def assign_tier(scope, config=None, vendor_name="", intake_customer_data=False):
    """Route by hard triggers. The point score is only the backstop."""
    policy = merged_tiering(config)
    scope = dict(scope or {})
    uncertain = {norm_answer(item) for item in policy["uncertain_answers"]}
    fired = []

    def add(name):
        if trigger_floor(policy, name) and name not in fired:
            fired.append(name)

    q2_kind = answer_kind(scope.get("q2_handles_data"), uncertain) if "q2_handles_data" in scope or not intake_customer_data else "blank"
    if "q2_handles_data" not in scope and not intake_customer_data:
        q2_kind = "blank"
    if intake_customer_data:
        q2 = "yes"
    elif q2_kind in ("yes", "other"):
        q2 = "yes"
    else:
        q2 = q2_kind

    blanks = []
    for key in BLANK_KEYS:
        if key == "q3_data_types" and q2 == "no":
            continue
        if key == "q2_handles_data" and q2 == "yes":
            continue
        if key not in scope or is_blank(scope.get(key), uncertain):
            blanks.append(key)

    kinds = set() if "q3_data_types" in blanks else data_kinds(scope.get("q3_data_types"))
    if "phi" in kinds or "pci" in kinds or "regulated" in kinds:
        add("phi_pci_or_regulated")
    if "pii" in kinds or intake_customer_data:
        add("customer_or_employee_pii")
    if phrase_hit(scope.get("q1_purpose"), policy.get("call_recording_phrases")):
        add("customer_or_employee_pii")
    if answer_kind(scope.get("q4_ai_training"), uncertain) in ("yes", "other"):
        add("ai_training")
    if answer_kind(scope.get("q5_sso_or_oauth"), uncertain) in ("yes", "other"):
        add("sso_oauth_or_write_api")
    access = parse_access(scope.get("q6_access"), uncertain)
    if access == "privileged":
        add("privileged_access")
    elif access == "write_or_api":
        add("sso_oauth_or_write_api")
    if answer_kind(scope.get("q7_critical_impact"), uncertain) in ("yes", "other"):
        add("critical_impact")
    spend = parse_spend(scope.get("q8_spend"), uncertain) if "q8_spend" in scope or "q8_spend" in blanks else "blank"
    if "q8_spend" not in scope:
        spend = "blank"
    if spend != "blank" and spend >= float(policy["spend_threshold"]):
        add("spend_threshold")
    if answer_kind(scope.get("q10_subprocessors"), uncertain) in ("yes", "other"):
        add("subprocessors")

    countries = [] if "q9_countries" in blanks else split_list(scope.get("q9_countries"))
    sanctions = screen_sanctions(_names(scope, vendor_name), countries, policy)
    data_involved = q2 == "yes" or bool(kinds - {"public"}) or intake_customer_data
    if data_involved:
        for country in countries:
            sanctioned = country_in(country, policy.get("sanctioned_countries") or [])
            approved = country_in(country, policy.get("approved_countries") or [])
            if not sanctioned and not approved:
                add("unapproved_geography")
                break

    human_block = None
    refusal = {norm_answer(item) for item in policy.get("location_refusal_answers") or []}
    if data_involved and "q9_countries" not in blanks and norm_answer(scope.get("q9_countries")) in refusal:
        human_block = "processing_location_refused"
    banned = {norm_name(item) for item in policy.get("banned_categories") or []}
    category = norm_name(scope.get("category"))
    purpose = norm_name(scope.get("q1_purpose"))
    if category in banned or purpose in banned:
        human_block = "banned_category"

    if q2 == "no" or not kinds or kinds <= {"public"}:
        score = policy["score"].get("data_public_or_none", 0)
    elif kinds <= {"public", "internal"}:
        score = policy["score"].get("data_internal_only", 2)
    else:
        score = 0
    tier = tier_from_score(score, policy)
    for name in fired:
        tier = at_least(tier, trigger_floor(policy, name))
    if blanks and tier == "low":
        tier = "medium"
    if any(key in HIGH_GAP for key in blanks) and tier == "medium":
        tier = "high"
    if human_block:
        tier = "high"
    sanction_hit = sanctions["status"] == "confirmed"
    if sanction_hit:
        tier = "high"
    elif sanctions["status"] == "potential":
        tier = at_least(tier, "medium")

    route = list(policy["routes"].get(tier) or ["manager"])
    for name, roles in (policy.get("extra_approvers") or {}).items():
        if name not in fired:
            continue
        if name == "spend_threshold" and tier != "high":
            continue
        for role in roles:
            if role not in route:
                route.append(role)
    if sanctions["status"] == "potential":
        reviewer = policy.get("sanctions_reviewer") or "security"
        if reviewer not in route:
            route.append(reviewer)
    if not route:
        route = ["manager"]

    if sanction_hit:
        decision = "reject"
    elif human_block or tier != "low" or blanks or fired or sanctions["status"] == "potential":
        decision = "human"
    else:
        decision = "approve"
    ordered = [name for name in TRIGGER_ORDER if name in fired]
    return {
        "tier": tier,
        "score": score,
        "triggers": ordered,
        "blank": blanks,
        "sanctions": sanctions["status"],
        "sanction_matches": sanctions["matches"],
        "sanction_hit": sanction_hit,
        "human_block": human_block,
        "decision": decision,
        "route": route,
        "auto_reject": False,
    }


def outcome_text(result):
    triggers = ", ".join(result.get("triggers") or []) or "none"
    blank = ", ".join(result.get("blank") or []) or "none"
    block = result.get("human_block") or "none"
    return (
        f"tier={result['tier']}; decision={result['decision']}; score={result.get('score', 0)}; "
        f"triggers: {triggers}; blank: {blank}; sanctions: {result.get('sanctions')}; "
        f"human_block: {block}"
    )


def raise_one(tier):
    return TIERS[min(TIERS.index(tier) + 1, len(TIERS) - 1)]


def higher_tier(left, right):
    return TIERS[max(TIERS.index(left), TIERS.index(right))]


def mix_counts(tickets):
    counts = {"low": 0, "medium": 0, "high": 0, "untiered": 0}
    for ticket in tickets:
        tier = ticket.get("tier")
        name = tier.get("tier") if isinstance(tier, dict) else tier
        counts[name if name in counts else "untiered"] += 1
    return counts


def in_sample(request_id, percent):
    if not percent or percent <= 0:
        return False
    if percent >= 100:
        return True
    bucket = int(hashlib.sha256(request_id.encode()).hexdigest()[:8], 16) % 100
    return bucket < percent


def low_review_sample(tickets, policy):
    picked = []
    rate = policy.get("low_sample_percent") or 0
    for ticket in tickets:
        tier = ticket.get("tier") if isinstance(ticket.get("tier"), dict) else {}
        if tier.get("tier") != "low":
            continue
        if tier.get("re_tiered") or in_sample(ticket["request_id"], rate):
            picked.append(ticket["request_id"])
    return picked


def auto_review_sample(tickets, policy):
    picked = []
    rate = policy.get("auto_sample_percent") or 0
    for ticket in tickets:
        status = (ticket.get("verification") or {}).get("status")
        if status not in {"approved_auto", "auto_rejected"}:
            continue
        if in_sample(ticket["request_id"], rate):
            picked.append(ticket["request_id"])
    return picked


def format_mix(counts, low_ids, auto_ids):
    tiered = counts["low"] + counts["medium"] + counts["high"]

    def share(count):
        if not tiered:
            return "0%"
        return f"{round(100 * count / tiered)}%"

    return "\n".join([
        f"tier mix: low {counts['low']} ({share(counts['low'])}), "
        f"medium {counts['medium']} ({share(counts['medium'])}), "
        f"high {counts['high']} ({share(counts['high'])}), "
        f"untiered {counts['untiered']}",
        f"low sample for review: {', '.join(low_ids) or 'none'}",
        f"weekly auto-decision sample: {', '.join(auto_ids) or 'none'}",
    ])


def main(argv=None):
    import sys
    from scripts.verify_tier import main as verify_main
    return verify_main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    import sys
    sys.exit(main())
