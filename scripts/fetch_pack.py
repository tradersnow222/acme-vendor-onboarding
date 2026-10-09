import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from scripts import write_back
from scripts.check_pack import check_pack
from scripts.launch_research import API_URL, NO_KEY
from scripts.status import RUNS_DIR, append_audit_row
from scripts.ticket import TICKETS_DIR, read_ticket, ticket_path

PACKS_DIR = Path(__file__).resolve().parent.parent / "packs"
EXAMPLE = "example: python3 -m scripts.fetch_pack --ticket VR-0001"
FENCED_BLOCK = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
EPILOG = """examples:
  python3 -m scripts.fetch_pack --ticket VR-0001
      dry run: print the requests without sending them
  CURSOR_API_KEY=... python3 -m scripts.fetch_pack --ticket VR-0001 --live
      fetch the agent's final reply, save the pack and write it back to the ticket
  python3 -m scripts.fetch_pack --ticket VR-0001 --reply-file reply.md
      same, but read the final reply from a saved file instead of the API"""


def extract_pack(text):
    pack = fetch_log = None
    for block in FENCED_BLOCK.findall(text):
        if block.startswith("url,http_status,fetched_at"):
            fetch_log = block
            continue
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and "rows" in data:
            pack = data
    return pack, fetch_log


def send_get(url, api_key):
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def print_dry_run(agent_id):
    print(f"GET {API_URL}/{agent_id}")
    print(f"GET {API_URL}/{agent_id}/runs/<latestRunId>")
    print('Authorization: Basic base64("<CURSOR_API_KEY>:")')
    print()
    print("Dry run: nothing was sent. Add --live to fetch the research pack.")


def usage_error(message):
    print(f"{message}\n{EXAMPLE}", file=sys.stderr)
    return 2


def read_live_reply(request_id, agent_id):
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        print(NO_KEY, file=sys.stderr)
        return 2, None
    try:
        agent = send_get(f"{API_URL}/{agent_id}", api_key)
        run = send_get(f"{API_URL}/{agent_id}/runs/{agent['latestRunId']}", api_key)
    except urllib.error.HTTPError as error:
        print(f"Cursor API error {error.code}", file=sys.stderr)
        return 1, None
    except urllib.error.URLError as error:
        print(f"Cursor API unreachable: {error.reason}", file=sys.stderr)
        return 1, None
    if run["status"] in ("CREATING", "RUNNING"):
        print(f"{request_id}: research run {run['id']} is {run['status']}; try again later")
        return 3, None
    if run["status"] != "FINISHED":
        print(f"{request_id}: research run {run['id']} is {run['status']}; no pack to fetch")
        return 1, None
    return 0, run.get("result") or ""


def main(argv):
    parser = argparse.ArgumentParser(
        description="Fetch the research pack from the research agent's final reply and write it back to the ticket.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ticket", help="request id of the ticket, e.g. VR-0001")
    parser.add_argument("--tickets-dir", default=TICKETS_DIR, help="folder the ticket files live in")
    parser.add_argument("--packs-dir", default=PACKS_DIR, help="folder to save the pack under")
    parser.add_argument("--runs-dir", default=RUNS_DIR, help="folder the audit logs live in")
    parser.add_argument("--reply-file", help="read the final reply from this file instead of the API")
    parser.add_argument("--live", action="store_true", help="call the Cursor API (default is a dry run)")
    args = parser.parse_args(argv)

    if not args.ticket:
        return usage_error("--ticket is required")
    if not ticket_path(args.ticket, args.tickets_dir).is_file():
        return usage_error(f"no ticket {args.ticket} in {args.tickets_dir}")
    ticket = read_ticket(args.ticket, args.tickets_dir)
    research = ticket["research"]
    if research.get("status") == "done":
        print(f"{args.ticket}: pack already written back: {research['pack_path']}")
        return 0

    if args.reply_file:
        reply = Path(args.reply_file).read_text()
    elif args.live:
        if not research.get("agent_id"):
            print(f"{args.ticket} has no research agent; run "
                  f"python3 -m scripts.launch_research --ticket {args.ticket} --live first", file=sys.stderr)
            return 2
        code, reply = read_live_reply(args.ticket, research["agent_id"])
        if code:
            return code
    else:
        print_dry_run(research.get("agent_id") or "<agent_id>")
        return 0

    pack, fetch_log = extract_pack(reply)
    if pack is None:
        print(f"{args.ticket}: no pack.json block in the agent's final reply")
        return 1
    if pack.get("request_id") != ticket["request_id"]:
        print(f"{args.ticket}: pack is for {pack.get('request_id')!r}, not {args.ticket}; nothing written")
        return 1

    pack_dir = Path(args.packs_dir) / args.ticket
    pack_dir.mkdir(parents=True, exist_ok=True)
    pack_path = pack_dir / "pack.json"
    pack_path.write_text(json.dumps(pack, indent=2) + "\n")
    if fetch_log is not None:
        (pack_dir / "fetch_log.csv").write_text(fetch_log)
    code = write_back.main(["--ticket", args.ticket, "--pack", str(pack_path), "--tickets-dir", str(args.tickets_dir)])
    result = check_pack(pack["rows"])
    if result["passed"]:
        outcome = f"pack check PASS ({len(pack['rows'])} rows, {result['not_found']} not_found)"
    else:
        outcome = f"pack check FAIL: {'; '.join(result['reasons'])}"
    append_audit_row(args.ticket, {
        "step": "Research pack built",
        "actor_type": "model",
        "actor": f"Cursor cloud agent {'reply-file' if args.reply_file else research['agent_id']}",
        "timestamp_pt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "outcome": outcome,
        "data_label": "PUBLIC",
    }, args.runs_dir)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
