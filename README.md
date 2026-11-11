# Vendor onboarding

A company can fork this repo and run vendor onboarding on its own machine: check intake, open a ticket, launch a research pack, route an approval, and record the decision. No extra services. Python 3.9 or newer and the standard library only.

Acme is a demo company with synthesized people. `config/company.json` and `data/samples/` ship filled with those demo values.

## Quickstart

Prerequisites: Python 3.9 or newer, git, and make. No pip installs. Run every command from the repo root.

### Environment variables

Set at most these. The sample walk below needs none of them.

| Variable | When |
|---|---|
| `VENDOR_ONBOARDING_REPO` | Repo URL the research agent clones. Default is `git remote get-url origin`, with any credentials removed. |
| `CURSOR_API_KEY` | Only if you pass `--live`. Dry run is the default and sends nothing. |

### Set your company

Edit `config/company.json`:

- `company_name`
- `approvers` — one string per role: `Name [SYNTHESIZED], Title`. Include manager, security, and any other role you use.
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

Built by Matt Snow on Grok Bot.
