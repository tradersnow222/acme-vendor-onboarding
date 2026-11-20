"""Independent check before any auto-approve or auto-reject.

Triage writes the evidence and a proposal. That proposal does not count.
Two verifier functions see only the raw evidence, not the triage notes.
Auto-decide is off unless the company sets tiering.auto_decide. The kill
switch is auto_decide false, which sends every case to a named human.

A verifier is a plain function: verify(evidence, config) -> dict.
Tests pass their own functions. The defaults are local list and phrase checks.
No network and no model call.

Applied rules: approval-policy.mdc (a named person stays accountable; silence
on the fast-lane clock is not a yes), status-and-audit.mdc, data-boundaries.mdc.
"""

import argparse
import json
from datetime import datetime, timedelta

from scripts.approvals import load_config
from scripts.status import RUNS_DIR, append_audit_row
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path
from scripts.tier import (
    assign_tier, format_mix, higher_tier, low_review_sample, auto_review_sample,
    merged_tiering, mix_counts, outcome_text, phrase_hit, raise_one, same_person,
)
from scripts.write_back import write_ticket

VERIFIERS = {}


def verifier(name):
    def wrap(fn):
        VERIFIERS[name] = fn
        return fn
    return wrap


def evidence_snapshot(evidence):
    return {
        "answers": evidence.get("answers") or {},
        "vendor_name": evidence.get("vendor_name") or "",
        "intake_customer_data": bool(evidence.get("intake_customer_data")),
        "vendor_docs": evidence.get("vendor_docs") or {},
    }


def evidence_hash(evidence):
    import hashlib
    blob = json.dumps(evidence_snapshot(evidence), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def verifier_view(evidence):
    """Raw evidence only. Triage notes are not included."""
    return evidence_snapshot(evidence)


def missing_docs(evidence, policy):
    docs = evidence.get("vendor_docs") or {}
    checked = set(docs.get("checked") or [])
    return [name for name in policy.get("required_docs") or [] if name not in checked]


def _with_doc_facts(evidence, config):
    """Copy the answers and raise them where the vendor docs contradict a No."""
    policy = merged_tiering(config)
    answers = dict((evidence.get("answers") or {}))
    reasons = []
    docs = evidence.get("vendor_docs") or {}
    scopes = " ".join(str(item) for item in (docs.get("oauth_scopes") or []))
    from scripts.tier import answer_kind, norm_answer
    uncertain = {norm_answer(item) for item in policy["uncertain_answers"]}
    if phrase_hit(scopes, policy.get("sensitive_oauth_markers")):
        if answer_kind(answers.get("q5_sso_or_oauth"), uncertain) not in ("yes", "other"):
            answers["q5_sso_or_oauth"] = "yes"
            reasons.append("oauth scopes contradict the intake answer")
    policy_text = str(docs.get("privacy_policy") or "")
    if phrase_hit(policy_text, policy.get("privacy_data_phrases")):
        if answer_kind(answers.get("q2_handles_data"), uncertain) != "yes":
            answers["q2_handles_data"] = "yes"
            reasons.append("privacy policy contradicts the intake answer")
        if phrase_hit(policy_text, policy.get("call_recording_phrases")):
            answers["q3_data_types"] = "employee personal data"
            reasons.append("privacy policy says the vendor records calls")
        elif answer_kind(answers.get("q3_data_types"), uncertain) in ("blank", "no"):
            answers["q3_data_types"] = "customer personal data"
    return answers, reasons


def derive(evidence, config):
    answers, reasons = _with_doc_facts(evidence, config)
    result = assign_tier(
        answers, config,
        vendor_name=evidence.get("vendor_name") or "",
        intake_customer_data=bool(evidence.get("intake_customer_data")),
    )
    if result["sanction_hit"]:
        reasons.append("confirmed sanctions match")
    if reasons:
        reasons.append("triggers: " + ", ".join(result["triggers"] or ["none"]))
    else:
        reasons.append(outcome_text(result))
    return {
        "tier": result["tier"],
        "decision": result["decision"],
        "reasons": reasons,
        "sanction_hit": result["sanction_hit"],
        "result": result,
    }


@verifier("rules")
def verify_rules(evidence, config):
    found = derive(evidence, config)
    found["verifier"] = "rules"
    return found


@verifier("docs")
def verify_docs(evidence, config):
    found = derive(evidence, config)
    found["verifier"] = "docs"
    found["reasons"] = [item for item in found["reasons"] if "contradict" in item or "policy" in item or "sanctions" in item] or found["reasons"]
    return found


def triage(evidence, config):
    """Proposal from the intake answers. Vendor-doc contradictions are not applied. Does not count."""
    result = assign_tier(
        evidence.get("answers") or {}, config,
        vendor_name=evidence.get("vendor_name") or "",
        intake_customer_data=bool(evidence.get("intake_customer_data")),
    )
    return {
        "tier": result["tier"],
        "decision": result["decision"],
        "reasons": [outcome_text(result)],
        "sanction_hit": result["sanction_hit"],
        "result": result,
        "counts": False,
    }


def label_verdict(proposal, found):
    agrees = found["tier"] == proposal["tier"] and found["decision"] == proposal["decision"]
    return {**found, "verdict": "PASS" if agrees else "FAIL"}


def adjudicate(proposal, verdicts, evidence, config, failed_rounds):
    policy = merged_tiering(config)
    missing = missing_docs(evidence, policy)
    checked = derive(verifier_view(evidence), config)
    agree = bool(verdicts) and len(verdicts) >= 2 and all(item["verdict"] == "PASS" for item in verdicts)
    floor = checked["tier"]
    for item in verdicts:
        floor = higher_tier(floor, item["tier"])
    if missing or not agree:
        tier = higher_tier(raise_one(proposal["tier"]), floor)
        failed = failed_rounds + 1
        stop = failed >= int(policy.get("max_verify_rounds") or 3)
        return {
            "action": "human", "tier": tier, "stop": stop, "failed_rounds": failed,
            "reason": "missing evidence" if missing else "verifiers disagree with triage",
            "checked_tier": checked["tier"],
            "route": list((checked.get("result") or {}).get("route") or []),
        }
    if not policy.get("auto_decide"):
        return {
            "action": "human", "tier": floor, "stop": False, "failed_rounds": 0,
            "reason": "auto_decide is off",
            "checked_tier": checked["tier"],
            "route": list((checked.get("result") or {}).get("route") or []),
        }
    sanctions_ok = (
        proposal["decision"] == "reject"
        and checked["sanction_hit"]
        and all(item.get("sanction_hit") and item["decision"] == "reject" for item in verdicts)
    )
    if sanctions_ok:
        return {
            "action": "auto_reject", "tier": "high", "stop": False, "failed_rounds": 0,
            "reason": "confirmed sanctions match, both verifiers agree",
            "checked_tier": checked["tier"],
            "route": [],
        }
    low_ok = (
        proposal["decision"] == "approve"
        and proposal["tier"] == "low"
        and checked["decision"] == "approve"
        and checked["tier"] == "low"
    )
    if low_ok:
        return {
            "action": "pending_objection", "tier": "low", "stop": False, "failed_rounds": 0,
            "reason": "both verifiers agree this is low",
            "checked_tier": checked["tier"],
            "route": list(policy["routes"]["low"]),
        }
    return {
        "action": "human", "tier": floor, "stop": False, "failed_rounds": 0,
        "reason": "rule checks did not clear an auto-decision",
        "checked_tier": checked["tier"],
        "route": list((checked.get("result") or {}).get("route") or []),
    }


def _audit(request_id, at, step, outcome, evidence_hash_value, runs_dir, actor="scripts.verify_tier", actor_type="script"):
    append_audit_row(request_id, {
        "step": step,
        "actor_type": actor_type,
        "actor": actor,
        "timestamp_pt": at,
        "what_they_saw": evidence_hash_value,
        "outcome": outcome,
        "est_cost": "~0",
        "data_label": "SYNTHESIZED",
    }, runs_dir)


def run_verification(ticket, evidence, config, at, runs_dir, verifiers=None):
    policy = merged_tiering(config)
    digest = evidence_hash(evidence)
    previous = ticket.get("verification") or {}
    if previous.get("stopped") and previous.get("evidence_hash") == digest:
        return {"action": "human", "tier": previous.get("tier") or "high", "reason": "stopped after 3 failed rounds",
                "evidence_hash": digest, "verdicts": []}
    failed = 0 if previous.get("evidence_hash") != digest else int(previous.get("failed_rounds") or 0)
    void_hashes = list(previous.get("void_hashes") or [])
    if previous.get("evidence_hash") and previous.get("evidence_hash") != digest:
        void_hashes.append(previous["evidence_hash"])
    view = verifier_view(evidence)
    proposal = triage(evidence, config)
    pairs = verifiers if verifiers is not None else [
        (name, VERIFIERS[name]) for name in (policy.get("verifiers") or ["rules", "docs"])
    ]
    verdicts = []
    for name, fn in pairs:
        found = fn(view, config)
        found["verifier"] = found.get("verifier") or name
        verdicts.append(label_verdict(proposal, found))
    decision = adjudicate(proposal, verdicts, evidence, config, failed)
    path = evidence_path(ticket["request_id"], runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = dict(evidence_snapshot(evidence))
    stored["sanctions"] = {
        "status": proposal["result"]["sanctions"] if "result" in proposal else proposal.get("sanction_hit"),
        "matches": (proposal.get("result") or {}).get("sanction_matches") or [],
    }
    stored["checked"] = list((evidence.get("vendor_docs") or {}).get("checked") or [])
    path.write_text(json.dumps(stored, indent=2) + "\n")

    _audit(ticket["request_id"], at, "Triage",
           f"proposed {outcome_text(proposal['result'])}; verdict does not count; evidence_hash={digest}",
           digest, runs_dir)
    for item in verdicts:
        reasons = "; ".join(item.get("reasons") or [])
        _audit(ticket["request_id"], at, "Verifier",
               f"verifier={item['verifier']} verdict={item['verdict']} tier={item['tier']} "
               f"decision={item['decision']}; reasons: {reasons}; evidence_hash={digest}",
               digest, runs_dir)
    _audit(ticket["request_id"], at, "Verification",
           f"action={decision['action']}; tier={decision['tier']}; {decision['reason']}; evidence_hash={digest}",
           digest, runs_dir)

    if decision["action"] == "auto_reject":
        route = []
    elif decision.get("checked_tier") == decision["tier"] and decision.get("route"):
        route = list(decision["route"])
    else:
        route = list(policy["routes"].get(decision["tier"]) or ["manager"])
    if decision["action"] == "auto_reject":
        _remember_undo(ticket)
        ticket.update(closed_at=at, final_decision="rejected", auto_rejected=True,
                      auto_reject_reasons=["confirmed_sanctions"])
        route = []
    elif decision["action"] == "pending_objection":
        owner = route[0]
        hours = int(policy.get("objection_hours") or 24)
        until = (datetime.fromisoformat(at) + timedelta(hours=hours)).isoformat()
        decision["objection_until"] = until
        decision["owner_role"] = owner
        ticket["approvers"].setdefault(owner, {"name": None, "decision": "waiting", "at": None, "conditions": []})
        names = (config or load_config()).get("approvers") or {}
        ticket["approvers"][owner]["name"] = ticket["approvers"][owner].get("name") or names.get(owner)
    ticket["route"] = route
    ticket["tier"] = {
        "tier": decision["tier"],
        "triggers": (proposal.get("result") or {}).get("triggers") or [],
        "blank": (proposal.get("result") or {}).get("blank") or [],
        "sanctions": (proposal.get("result") or {}).get("sanctions"),
        "re_tiered": bool(previous),
        "at": at,
    }
    ticket["scope"] = dict(evidence.get("answers") or {})
    ticket["vendor_docs"] = evidence.get("vendor_docs") or {}
    public_verdicts = [{
        "verifier": item["verifier"], "verdict": item["verdict"], "tier": item["tier"],
        "decision": item["decision"], "reasons": item.get("reasons") or [], "evidence_hash": digest,
        "sanction_hit": bool(item.get("sanction_hit")),
    } for item in verdicts]
    status = {
        "auto_reject": "auto_rejected",
        "pending_objection": "pending_objection",
        "human": "stopped" if decision.get("stop") else "human",
    }[decision["action"]]
    ticket["verification"] = {
        "status": status,
        "tier": decision["tier"],
        "evidence_hash": digest,
        "evidence_file": str(path),
        "rounds": int(previous.get("rounds") or 0) + 1,
        "failed_rounds": decision["failed_rounds"],
        "stopped": bool(decision.get("stop")),
        "void_hashes": void_hashes,
        "triage": {"tier": proposal["tier"], "decision": proposal["decision"], "counts": False},
        "verdicts": public_verdicts,
        "reason": decision["reason"],
        "objection_until": decision.get("objection_until"),
        "owner_role": decision.get("owner_role"),
    }
    decision["evidence_hash"] = digest
    decision["verdicts"] = public_verdicts
    decision["proposal"] = proposal
    return decision


def evidence_path(request_id, runs_dir):
    from pathlib import Path
    return Path(runs_dir) / request_id / "evidence.json"


def _remember_undo(ticket):
    if ticket.get("undo"):
        return
    verification = ticket.get("verification") or {}
    ticket["undo"] = {
        "closed_at": ticket.get("closed_at"),
        "final_decision": ticket.get("final_decision"),
        "auto_rejected": ticket.get("auto_rejected", False),
        "auto_reject_reasons": list(ticket.get("auto_reject_reasons") or []),
        "route": list(ticket.get("route") or []),
        "verification_status": verification.get("status"),
    }


def revert_auto(ticket):
    undo = ticket.get("undo")
    if not undo:
        raise ValueError("nothing to revert")
    if undo.get("closed_at"):
        ticket["closed_at"] = undo["closed_at"]
    else:
        ticket.pop("closed_at", None)
    if undo.get("final_decision"):
        ticket["final_decision"] = undo["final_decision"]
    else:
        ticket.pop("final_decision", None)
    if undo.get("auto_rejected"):
        ticket["auto_rejected"] = True
        ticket["auto_reject_reasons"] = list(undo.get("auto_reject_reasons") or [])
    else:
        ticket.pop("auto_rejected", None)
        ticket.pop("auto_reject_reasons", None)
    ticket["route"] = list(undo.get("route") or [])
    if ticket.get("verification") is not None:
        ticket["verification"]["status"] = "human"
    ticket.pop("undo", None)
    ticket["reverted"] = True


def object_to_auto(ticket, by, reason, config=None):
    verification = ticket.get("verification") or {}
    if verification.get("status") != "pending_objection":
        raise ValueError("no pending auto-approval")
    policy = merged_tiering(config)
    owner_role = verification.get("owner_role") or policy["routes"]["low"][0]
    owner = ((config or load_config()).get("approvers") or {}).get(owner_role, "")
    requester = ticket.get("requester") or ""
    if requester and same_person(by, requester):
        raise ValueError("the requester cannot clear their own request")
    if owner and not same_person(by, owner):
        raise ValueError("objection must come from the named owner")
    verification["status"] = "human"
    verification["objection"] = {"by": by, "reason": reason}
    ticket["verification"] = verification
    tier = higher_tier(verification.get("tier") or "low", "medium")
    ticket["route"] = list(policy["routes"][tier])
    ticket["tier"]["tier"] = tier
    return tier


def apply_pending(ticket, now, config=None):
    verification = ticket.get("verification") or {}
    if verification.get("status") != "pending_objection":
        return False
    if not merged_tiering(config).get("auto_decide"):
        return False
    until = verification.get("objection_until")
    if not until or datetime.fromisoformat(now) < datetime.fromisoformat(until):
        return False
    _remember_undo(ticket)
    ticket.update(closed_at=now, final_decision="approved")
    verification["status"] = "approved_auto"
    ticket["verification"] = verification
    return True


def build_evidence(ticket, answers, vendor_docs, config=None):
    field = ((config or load_config()).get("data_sensitivity") or {}).get("intake_field", "touches_customer_data")
    try:
        intake_yes = ticket["intake"][field]["value"] is True
    except (KeyError, TypeError):
        intake_yes = False
    vendor = ((ticket.get("intake") or {}).get("vendor_legal_name") or {}).get("value") or ""
    return {
        "answers": dict(answers or {}),
        "vendor_name": vendor,
        "intake_customer_data": intake_yes,
        "vendor_docs": vendor_docs or {},
    }


def _parse_answers(pairs):
    answers = {}
    for item in pairs or []:
        if "=" not in item:
            raise ValueError(f"answer needs key=value: {item}")
        key, value = item.split("=", 1)
        answers[key.strip()] = value.strip()
    return answers


def main(argv):
    parser = argparse.ArgumentParser(
        description="Apply the company tiering policy, or print the tier mix.",
    )
    parser.add_argument("--ticket")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR)
    parser.add_argument("--runs-dir", default=RUNS_DIR)
    parser.add_argument("--config", default=None)
    parser.add_argument("--at", default=datetime.now().astimezone().isoformat(timespec="seconds"))
    parser.add_argument("--answer", action="append", default=[])
    parser.add_argument("--oauth", action="append", default=[])
    parser.add_argument("--privacy", default="")
    parser.add_argument("--checked", action="append", default=[])
    parser.add_argument("--requester", default="")
    parser.add_argument("--renew", action="store_true")
    parser.add_argument("--mix", action="store_true")
    parser.add_argument("--object", action="store_true")
    parser.add_argument("--by")
    parser.add_argument("--reason")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--apply-pending", action="store_true")
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.mix:
        from pathlib import Path
        folder = Path(args.tickets_dir)
        tickets = [read_ticket(path.stem, folder) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []
        policy = merged_tiering(config)
        print(format_mix(mix_counts(tickets), low_review_sample(tickets, policy), auto_review_sample(tickets, policy)))
        return 0

    if not args.ticket:
        print("usage: python3 -m scripts.tier --ticket VR-0002 --answer q5_sso_or_oauth=no", flush=True)
        print("       python3 -m scripts.tier --mix --tickets-dir tickets", flush=True)
        return 2
    if not ticket_path(args.ticket, args.tickets_dir).is_file():
        print(f"no ticket {args.ticket} in {args.tickets_dir}")
        return 2
    try:
        if datetime.fromisoformat(args.at).tzinfo is None:
            raise ValueError
    except ValueError:
        print(f"--at needs an ISO 8601 time with a UTC offset: {args.at}")
        return 2

    ticket = read_ticket(args.ticket, args.tickets_dir)
    if args.requester:
        ticket["requester"] = args.requester

    if args.object:
        if not args.by or not args.reason:
            print("objection needs --by and --reason")
            return 2
        try:
            object_to_auto(ticket, args.by, args.reason, config)
        except ValueError as error:
            print(f"{args.ticket}: not recorded: {error}")
            return 1
        write_ticket(ticket, args.ticket, args.tickets_dir)
        digest = (ticket.get("verification") or {}).get("evidence_hash") or "-"
        _audit(args.ticket, args.at, "Objection", f"{args.by}: {args.reason}; evidence_hash={digest}",
               digest, args.runs_dir, actor=args.by, actor_type="person")
        print(f"{args.ticket}: objection recorded; routed to a named human")
        return 0

    if args.revert:
        try:
            revert_auto(ticket)
        except ValueError as error:
            print(f"{args.ticket}: {error}")
            return 1
        write_ticket(ticket, args.ticket, args.tickets_dir)
        _audit(args.ticket, args.at, "Revert", "one-step revert of the last auto-decision",
               (ticket.get("verification") or {}).get("evidence_hash") or "-", args.runs_dir)
        print(f"{args.ticket}: reverted one step")
        return 0

    if args.apply_pending:
        now = args.now or args.at
        applied = apply_pending(ticket, now, config)
        if not applied:
            print(f"{args.ticket}: no auto-approval to apply")
            return 0
        write_ticket(ticket, args.ticket, args.tickets_dir)
        owner = (ticket.get("verification") or {}).get("owner_role") or "manager"
        _audit(args.ticket, now, "Auto-approve",
               f"objection window elapsed; low approval takes effect; named owner notified: {owner}",
               (ticket.get("verification") or {}).get("evidence_hash") or "-", args.runs_dir)
        print(f"{args.ticket}: low approval has taken effect after the objection window")
        return 0

    answers = dict(ticket.get("scope") or {})
    try:
        answers.update(_parse_answers(args.answer))
    except ValueError as error:
        print(error)
        return 2
    docs = dict(ticket.get("vendor_docs") or {})
    if args.oauth:
        docs["oauth_scopes"] = list(args.oauth)
    if args.privacy:
        docs["privacy_policy"] = args.privacy
    checked = list(docs.get("checked") or [])
    checked.extend(args.checked)
    if args.oauth and "oauth_scopes" not in checked:
        checked.append("oauth_scopes")
    if args.privacy and "privacy_policy" not in checked:
        checked.append("privacy_policy")
    if checked:
        docs["checked"] = checked
    if not answers and not args.renew:
        print("pass --answer key=value, --renew, or --mix")
        return 2
    evidence = build_evidence(ticket, answers, docs, config)
    decision = run_verification(ticket, evidence, config, args.at, args.runs_dir)
    try:
        write_ticket(ticket, args.ticket, args.tickets_dir)
    except Exception as error:
        print(error)
        return 1
    if decision["action"] == "pending_objection":
        _notify(ticket, [decision["owner_role"]], config)
        print(f"{args.ticket}: pending objection by {decision['owner_role']} until {decision['objection_until']}; "
              f"approval has not taken effect")
    elif decision["action"] == "auto_reject":
        print(f"{args.ticket}: auto-rejected (confirmed_sanctions); evidence_hash={decision['evidence_hash']}")
    else:
        print(f"{args.ticket}: {decision['reason']}; tier {decision['tier']}; route {', '.join(ticket.get('route') or []) or 'none'}")
    return 0


def _notify(ticket, roles, config):
    try:
        from scripts.approval_notice import notify_requested
        notify_requested(ticket, roles, config or load_config())
    except Exception as error:
        import sys
        print(f"approval notice: failed: {type(error).__name__}", file=sys.stderr)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
