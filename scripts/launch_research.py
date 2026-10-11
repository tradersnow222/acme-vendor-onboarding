import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

from scripts.status import RUNS_DIR, append_audit_row
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path

API_URL = "https://api.cursor.com/v1/agents"
REPO_URL = "https://github.com/tradersnow222/acme-vendor-onboarding"
EXAMPLE = "example: python3 -m scripts.launch_research --ticket VR-0001"
NO_KEY = "CURSOR_API_KEY is not set; export it or run without --live for a dry run"
EPILOG = """examples:
  python3 -m scripts.launch_research --ticket VR-0001
      dry run: print the request without sending it
  CURSOR_API_KEY=... python3 -m scripts.launch_research --ticket VR-0001 --live
      launch the research agent and record it on the ticket"""


def build_prompt(ticket):
    request_id = ticket["request_id"]
    intake = ticket["intake"]
    return (
        f"Write {request_id} to .research_ticket_id before starting. "
        f"Follow .cursor/skills/build-research-pack/SKILL.md for request {request_id}. "
        f"The vendor is {intake['vendor_legal_name']['value']} ({intake['website']['value']}). "
        f"Write only under packs/{request_id}/. Use public pages only. "
        "Do not edit any other file. Do not open a pull request. "
        f"End your final reply with packs/{request_id}/pack.json in one ```json fenced block "
        f"and packs/{request_id}/fetch_log.csv in one ```csv fenced block whose first line is url,http_status,fetched_at. "
        "Put each fence on its own line and nothing else inside the blocks."
    )


def build_body(ticket, model=None):
    body = {
        "prompt": {"text": build_prompt(ticket)},
        "repos": [{"url": REPO_URL, "startingRef": "main"}],
        "autoCreatePR": False,
    }
    if model:
        body["model"] = {"id": model}
    return body


def send_request(body, api_key):
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def write_ticket(ticket, tickets_dir):
    ticket_path(ticket["request_id"], tickets_dir).write_text(json.dumps(ticket, indent=2) + "\n")


def print_dry_run(body):
    print(f"POST {API_URL}")
    print('Authorization: Basic base64("<CURSOR_API_KEY>:")')
    print("Content-Type: application/json")
    print()
    print(json.dumps(body, indent=2))
    print()
    print("Dry run: nothing was sent. Add --live to launch the research agent.")


def main(argv):
    parser = argparse.ArgumentParser(
        description="Launch a Cursor cloud agent that builds the research pack for a ticket.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ticket", help="request id of the ticket, e.g. VR-0001")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the ticket files live in")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder the audit logs live in")
    parser.add_argument("--model", help="model id for the agent; omit to use the account default")
    parser.add_argument("--live", action="store_true", help="send the request (default is a dry run)")
    args = parser.parse_args(argv)

    if not args.ticket:
        print(f"--ticket is required. {EXAMPLE}", file=sys.stderr)
        return 2
    if not ticket_path(args.ticket, args.tickets_dir).is_file():
        print(f"no ticket file for {args.ticket} in {args.tickets_dir}. {EXAMPLE}", file=sys.stderr)
        return 2

    ticket = read_ticket(args.ticket, args.tickets_dir)
    research = ticket["research"]
    if research.get("agent_id"):
        print(f"{args.ticket}: research agent already started: {research['agent_id']} {research['agent_url']}")
        return 0

    body = build_body(ticket, args.model)
    if not args.live:
        print_dry_run(body)
        return 0

    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        print(NO_KEY, file=sys.stderr)
        return 2

    try:
        response = send_request(body, api_key)
    except urllib.error.HTTPError as error:
        print(f"Cursor API error {error.code}: {error.read().decode()}", file=sys.stderr)
        return 1

    agent = response["agent"]
    research.update({
        "agent_id": agent["id"],
        "agent_url": agent["url"],
        "run_id": response["run"]["id"],
        "launched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    write_ticket(ticket, args.tickets_dir)
    append_audit_row(args.ticket, {
        "step": "Research launched",
        "actor_type": "script",
        "actor": "scripts.launch_research",
        "timestamp_pt": research["launched_at"],
        "outcome": f"agent {agent['id']} started",
        "data_label": "PUBLIC",
    }, args.runs_dir)
    print(f"{args.ticket}: research agent started: {agent['id']} {agent['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
