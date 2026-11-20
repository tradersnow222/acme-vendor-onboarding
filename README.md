# Vendor onboarding

A company can fork this repo and run vendor onboarding on its own machine: check intake, open a ticket, launch a research pack, route an approval, and record the decision. No extra services. Python 3.9 or newer and the standard library only.

Acme is a demo company with synthesized people. `config/company.json` and `data/samples/` ship filled with those demo values.

To run one review with your own company, follow [PILOT.md](PILOT.md).

## Quickstart

Prerequisites: Python 3.9 or newer, git, and make. No pip installs. Run every command from the repo root.

### Environment variables

The sample walk below needs none of them. Slack and email notices stay off until the `APPROVAL_` variables in [DATA-HANDLING.md](DATA-HANDLING.md) are set.

| Variable | When |
|---|---|
| `VENDOR_ONBOARDING_CONFIG` | Path to your company JSON. Default is `config/company.json`. See [PILOT.md](PILOT.md). |
| `VENDOR_ONBOARDING_REPO` | Repo URL the research agent clones. Default is `git remote get-url origin`, with any credentials removed. |
| `CURSOR_API_KEY` | Only if you pass `--live`. Dry run is the default and sends nothing. |
| `APPROVAL_SLACK_WEBHOOK_URL` | Slack incoming webhook for an approval notice. Unset skips Slack. |
| `APPROVAL_SMTP_HOST` | SMTP host for an approval notice. Unset skips email. Port, user, password, and from are in [DATA-HANDLING.md](DATA-HANDLING.md). |
| `APPROVAL_REVIEW_BASE_URL` | Prefix of the review link in an approval notice. |

### Set your company

Edit `config/company.json`:

- `company_name`
- `approvers` — one string per role: `Name [SYNTHESIZED], Title`. Include manager, security, and any other role you use.
- `approver_emails` — optional address per role, used when email notices are on. The demo uses `@example.com` placeholders.
- `always_route` — roles that always approve. The demo is `["manager"]`. Add a role here when it should approve every vendor.
- `stale_after_hours` — hours of silence before a nudge. Silence is never a yes.
- `data_sensitivity` — which intake field and pack flag add `security_role`. The demo adds security when `touches_customer_data` is true or the pack flag `r3_shows_personal_data` is true.

### One vendor, using the Figma sample

The sample start date is 2026-10-26, so these commands pin the clock to 2026-10-09. Research stays a dry run. The pack is the committed sample, loaded through `--reply-file`.

```bash
make setup
python3 -m scripts.intake_check figma --today 2026-10-09
python3 -m scripts.ticket figma
python3 -m scripts.launch_research --ticket VR-0002
python3 - <<'PY'
import json
from pathlib import Path
sample = json.loads(Path("data/samples/vr-0002-figma.json").read_text())
pack = {"request_id": sample["request_id"], "rows": sample["expected"]["pack"]["rows"]}
log = Path("data/samples/vr-0002-figma-fetch-log.csv").read_text()
path = Path("runs/quickstart")
path.mkdir(parents=True, exist_ok=True)
(path / "reply.md").write_text(
    "```json\n" + json.dumps(pack, indent=2) + "\n```\n\n```csv\n" + log + "```\n"
)
PY
python3 -m scripts.fetch_pack --ticket VR-0002 --reply-file runs/quickstart/reply.md
python3 -m scripts.request_approvals --ticket VR-0002 --at 2026-10-09T14:00:00-07:00 --today 2026-10-09
python3 -m scripts.record_approval --ticket VR-0002 --role manager \
  --name "Daniel Okafor [SYNTHESIZED]" --decision approved \
  --quote "Approved for the 90-day pilot." --at 2026-10-09T14:50:00-07:00
python3 -m scripts.ticket --close VR-0002 --at 2026-10-09T14:51:00-07:00
python3 -m scripts.status --ticket VR-0002
```

Use your approver's own name and words. The script only records a decision a named person already gave.

The sample decision times are 2026-10-09. A ticket created on a later day and closed at that sample time can show a negative days-open. The recorded decision is still `approved`.

Tickets land in `tickets/`, packs in `packs/`, and the audit log at `runs/<id>/audit.csv`. See [DATA-HANDLING.md](DATA-HANDLING.md). The longer demo writeup is in [INTERVIEW.md](INTERVIEW.md).

## Tiering

`config/company.json` holds a tiering policy the company sets, under `tiering`. The script applies the triggers, score bands, routes, and lists in that file.

Inherent risk picks the route. Residual risk is the named person's accept, reject, or conditions. A SOC 2 report does not drop the tier.

The five intake fields still gate the request. Tiering adds 11 factual questions (purpose, data, AI training, SSO or OAuth, access, impact, spend, country, subprocessors, and a named budget owner). The script never asks the requester to name a tier. The bot runs the sanctions screen from the lists in the config. It does not call the network.

Any one hard trigger blocks Low. Blank, missing, or "not sure" on the data questions moves the ticket up. Medium triggers are configurable (`enabled` true or false), not only the spend threshold. High adds Legal and Privacy. Spend at or over `spend_threshold` (demo default 10000) is at least Medium.

Low is a fast lane: one named approver who is not the requester, and a clock. `fast_lane_hours` defaults to `stale_after_hours` (20 in the Acme demo). The research note of 2 business days is unverified; set `fast_lane_hours` to 48 to use two 24-hour days. When the clock runs out, the ticket escalates to Security. Silence is not a yes, and a timeout never auto-approves.

Before any auto-approve or auto-reject, two checks the company configures re-read the evidence file (`runs/<id>/evidence.json`: each intake answer, the sanctions result, and which vendor docs were checked). They do not see the triage notes. They look for contradictions, such as OAuth scopes or a privacy policy that describe data the intake said was absent. Each writes PASS or FAIL, pinned to a hash of that snapshot. If the answers or the docs change, those verdicts are void and the check runs again.

`auto_decide` defaults to false. That flag is the kill switch: every auto-decision goes back to a named human. With it on, an auto-decision still needs the rule checks and both verifiers to agree with triage. Disagreement or missing docs escalates one tier. After 3 failed rounds the ticket stops on a human route.

Auto-approve is only for Low. The named owner gets a notice and an objection window (`objection_hours`, default 24, a stand-in for 1 business day) before `python3 -m scripts.tier --apply-pending` lets it take effect. Auto-reject is only a confirmed sanctions match that both verifiers confirm on their own. A banned category, a refused processing location, or a potential sanctions match goes to a named human.

Re-check with `python3 -m scripts.tier --ticket <id> --renew` or new `--answer` values when data, users, SSO, AI use, subprocessors, geography, or spend change. `python3 -m scripts.tier --mix` prints the Low, Medium, and High share. A weekly sample of auto-decisions, and a sample of Low files, are listed for a person to review (`auto_sample_percent`, `low_sample_percent`).

Every verdict, evidence hash, and verifier reason is a row in the audit CSV. A wrong call has one undo: `python3 -m scripts.tier --ticket <id> --revert`. Then add the missed fact to `tiering` and a case in `data/samples/tier-cases.json` with a test, so the same miss fails the suite next time.

Later, and not in this version: a hash-chained audit file, a business-day calendar, a live sanctions pull, reading scope out of the research pack, an offboarding checklist, a fourth tier, a formal waiver, near-threshold sampling, and SIG/CAIQ tracking.

Built by Matt Snow on Grok Bot.
