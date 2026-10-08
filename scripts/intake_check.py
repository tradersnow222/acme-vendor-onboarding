import argparse
import re
from datetime import date
from urllib.parse import urlparse

from scripts.samples import load_sample

FIELDS = ["vendor_legal_name", "website", "touches_customer_data", "business_owner", "target_start_date"]
LEGAL_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|plc|ag|sa|bv|lp|llp)\.?$", re.I)
VAGUE_OWNERS = {"me", "i", "us", "we", "myself"}


def _legal_name_ok(field):
    name = (field.get("value") or "").strip()
    if not name:
        return False
    if field.get("source_url"):
        return True
    return field.get("from") == "requester" and bool(LEGAL_SUFFIX.search(name))


def _website_ok(field):
    value = field.get("value")
    if not isinstance(value, str):
        return False
    url = urlparse(value.strip())
    return url.scheme == "https" and "." in url.netloc and " " not in value.strip()


def _customer_data_ok(field):
    return isinstance(field.get("value"), bool)


def _owner_ok(field):
    value = (field.get("value") or "").strip()
    if value.lower() in VAGUE_OWNERS or "team" in value.lower():
        return False
    name = value.split(",")[0].replace("[SYNTHESIZED]", "").split()
    return len(name) >= 2 and all(part[0].isupper() for part in name)


def _start_date_ok(field, today):
    value = field.get("value")
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value) >= today
    except ValueError:
        return False


def check_intake(fields, today):
    checks = {
        "vendor_legal_name": _legal_name_ok,
        "website": _website_ok,
        "touches_customer_data": _customer_data_ok,
        "business_owner": _owner_ok,
        "target_start_date": lambda field: _start_date_ok(field, today),
    }
    result = {"ask_for": [], "confirm": [], "fill_from_research": []}
    for name in FIELDS:
        field = fields.get(name) or {}
        if not checks[name](field):
            result["fill_from_research" if name == "vendor_legal_name" else "ask_for"].append(name)
        elif not field.get("confirmed"):
            result["confirm"].append(name)
    result["complete"] = not any(result.values())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the five required intake fields of a sample request.")
    parser.add_argument("sample", help="sample short name or request id, e.g. zendesk or VR-0001")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
    args = parser.parse_args(argv)
    sample = load_sample(args.sample)
    result = check_intake(sample["expected"]["intake"]["fields"], args.today)
    print(f"{sample['request_id']}: intake {'complete' if result['complete'] else 'incomplete'}")
    for key in ("ask_for", "confirm", "fill_from_research"):
        print(f"  {key.replace('_', ' ')}: {', '.join(result[key]) or 'none'}")


if __name__ == "__main__":
    main()
