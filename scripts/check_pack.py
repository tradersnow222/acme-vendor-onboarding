import csv
import re
import sys
from datetime import date
from pathlib import Path

from scripts.samples import load_sample, sample_fetch_log

REQUIRED_ITEMS = [f"R{n}" for n in range(1, 11)]
MUST_BE_FOUND = ["R1", "R3", "R4", "R10"]


def _item(row_id):
    match = re.fullmatch(r"(R\d+)[a-z]?", row_id or "")
    return match.group(1) if match else None


def _is_date(value):
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def _fetched_ok(fetch_log):
    with open(fetch_log, newline="") as f:
        return {line["url"] for line in csv.DictReader(f) if line["http_status"] == "200"}


def check_pack(rows, fetch_log=None):
    reasons = []
    seen = set()
    found = set()
    fetched_ok = _fetched_ok(fetch_log) if fetch_log and Path(fetch_log).is_file() else None
    for row in rows:
        row_id = row.get("id")
        item = _item(row_id)
        if item is None:
            reasons.append(f"{row_id!r} is not an R-row id")
        seen.add(item)
        status = row.get("status")
        if status == "found":
            found.add(item)
            if not row.get("value"):
                reasons.append(f"{row_id} is found but has no value")
        elif status != "not_found":
            reasons.append(f"{row_id} has bad status {status!r}")
        if not row.get("source_urls"):
            reasons.append(f"{row_id} has no source URL")
        if fetched_ok is not None:
            for url in row.get("source_urls") or []:
                if url not in fetched_ok:
                    reasons.append(f"{row_id} cites {url} without an HTTP 200 in the fetch log")
        if not _is_date(row.get("checked_date")):
            reasons.append(f"{row_id} has bad checked_date {row.get('checked_date')!r}")
    reasons += [f"{item} has no row" for item in REQUIRED_ITEMS if item not in seen]
    reasons += [f"{item} must be found" for item in MUST_BE_FOUND if item in seen and item not in found]
    not_found = sum(row.get("status") == "not_found" for row in rows)
    return {"passed": not reasons, "reasons": reasons, "not_found": not_found}


def main(argv):
    if len(argv) != 1:
        print("usage: python3 -m scripts.check_pack <sample>")
        return 2
    sample = load_sample(argv[0])
    rows = sample["expected"]["pack"]["rows"] or []
    result = check_pack(rows, sample_fetch_log(sample["request_id"]))
    verdict = "PASS" if result["passed"] else "FAIL"
    print(f"{sample['request_id']} {argv[0]}: {verdict} ({len(rows)} rows, {result['not_found']} not_found)")
    for reason in result["reasons"]:
        print(f"- {reason}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
