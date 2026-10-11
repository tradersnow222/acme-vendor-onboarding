import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "approvals.json"

TRANSITIONS = {
    "waiting": {"approved", "approved_with_conditions", "rejected"},
    "approved": set(),
    "approved_with_conditions": set(),
    "rejected": set(),
}

BLOCKED_NAME_WORDS = {"anonymous", "bot", "agent"}


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text())


def record_decision(approvers, role, name, decision, at, conditions):
    words = set(re.findall(r"[a-z]+", (name or "").lower()))
    if not words or words & BLOCKED_NAME_WORDS:
        raise ValueError(f"not a named person: {name!r}")
    if role not in approvers:
        raise ValueError(f"role {role!r} is not in the route")
    if decision not in TRANSITIONS:
        raise ValueError(f"unknown decision: {decision!r}")
    current = approvers[role]["decision"]
    if decision not in TRANSITIONS[current]:
        raise ValueError(f"cannot move {role} from {current} to {decision}")
    entry = {"name": name, "decision": decision, "at": at, "conditions": list(conditions)}
    return {**approvers, role: entry}


def content_hash(ticket):
    pack_path = ticket["research"].get("pack_path")
    pack = json.loads(Path(pack_path).read_text()) if pack_path else None
    blob = json.dumps({"intake": ticket["intake"], "pack": pack}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def cancel_changed_approvals(approvers, current_hash):
    cancelled = []
    for role, entry in approvers.items():
        if entry["decision"] in ("approved", "approved_with_conditions") and entry.get("hash") not in (None, current_hash):
            cancelled.append((role, entry))
            approvers[role] = {"name": entry["name"], "decision": "waiting", "at": None, "conditions": []}
    return cancelled


def overall_decision(approvers):
    decisions = [approver["decision"] for approver in approvers.values()]
    if "rejected" in decisions:
        return "rejected"
    if decisions and all(d in ("approved", "approved_with_conditions") for d in decisions):
        return "approved_with_conditions" if "approved_with_conditions" in decisions else "approved"
    return "waiting"


def is_stale(approver, waiting_since, now, config):
    waited = datetime.fromisoformat(now) - datetime.fromisoformat(waiting_since)
    return approver["decision"] == "waiting" and waited >= timedelta(hours=config["stale_after_hours"])
