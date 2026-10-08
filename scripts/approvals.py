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
