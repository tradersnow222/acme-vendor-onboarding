# Pilot: one vendor review for your company

This walkthrough is for someone who forked the repo and wants one completed vendor review with their own company config. You do not edit code. You do not need an API key. The research step is a dry run and sends nothing.

Acme in `config/company.json` is the demo company. This path uses a different fictional company, Northwind Goods, until you replace the names.

## What you need

Python 3.9 or newer, git, and make. No pip installs. Run every command from the repo root, after you clone your fork.

## 1. Point the scripts at your company

Pick one. Do not do both.

**Use it for real.** Copy the sample over the demo config and edit the copy:

```bash
cp examples/company.sample.json config/company.json
```

Then change `company_name`, `approvers`, and `stale_after_hours` in `config/company.json`. Leave `VENDOR_ONBOARDING_CONFIG` unset so the scripts read that file.

**Try the sample unchanged.** Keep the Acme demo file and point at the sample:

```bash
export VENDOR_ONBOARDING_CONFIG="$PWD/examples/company.sample.json"
```

`examples/company.sample.json` is ordinary JSON. Loading it needs no code change. Each field has a note under `_comments`. Scripts ignore `_comments`.

Fill these fields:

| Field | What to put |
|---|---|
| `company_name` | Your company's name. The digest prints it. |
| `demo` | `false` for a real company. |
| `note` | One line about this file. |
| `people_label` | `[SYNTHESIZED]` while names are examples. |
| `stale_after_hours` | Hours of silence before a nudge. Silence is never a yes. |
| `always_route` | Roles that approve every vendor. Keep `manager`. |
| `approvers` | One string per role: `Name [SYNTHESIZED], Title`. |
| `data_sensitivity` | When to add the security role. The notes in the sample say what each key does. |

The sample manager string, which the command below records, is `Priya Shah [SYNTHESIZED], Head of Operations`. If you edit `approvers.manager`, use your string in that command instead.

Other environment variables, only if you need them:

| Variable | When |
|---|---|
| `VENDOR_ONBOARDING_CONFIG` | Path to your company JSON. Unset means `config/company.json`. |
| `VENDOR_ONBOARDING_REPO` | Repo URL the research agent would clone. Default is `git remote get-url origin`, with any credentials removed. Leave it unset for this pilot. |
| `CURSOR_API_KEY` | Only for `--live`. Do not set it for this walkthrough. |

## 2. What you may type, and what you must not

A review may hold a vendor name, a contact (the named business owner), the product, the use case, and review notes (the approver's words and any conditions).

Never give it bank details, EIN/tax IDs, SSNs, passwords, contract PDFs, or customer data. Intake rejects a bank account number, a routing number, an EIN, a TIN, or an SSN and stores nothing. That rejection is covered by `tests/test_sensitive.py`. A reference such as `W-9 received` is the right substitute. See [DATA-HANDLING.md](DATA-HANDLING.md).

## 3. Run one review

These commands review the committed Figma sample. The clock is pinned to 2026-10-09 because that sample's start date is 2026-10-26. Research stays a dry run. The pack is the committed sample, loaded through `--reply-file`.

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
python3 -m scripts.digest --now 2026-10-09T14:10:00-07:00
python3 -m scripts.record_approval --ticket VR-0002 --role manager \
  --name "Priya Shah [SYNTHESIZED], Head of Operations" --decision approved \
  --quote "Approved for the 90-day pilot." --at 2026-10-09T14:50:00-07:00
python3 -m scripts.ticket --close VR-0002 --at 2026-10-09T14:51:00-07:00
python3 -m scripts.status --ticket VR-0002
```

Use your approver's own name and words when this is a real decision. The script only records a decision a named person already gave. It never approves on its own.

Tickets land in `tickets/`, packs in `packs/`, and the audit log at `runs/VR-0002/audit.csv`. Those folders are git-ignored. Do not commit them.

## 4. What success looks like

Intake prints `VR-0002: intake complete`.

The launch step prints `Dry run: nothing was sent.`

While the ticket is still open, the digest starts with your company name, not Acme:

```text
Northwind Goods vendor digest 2026-10-09: 1 open request(s)
```

After close-out, status starts:

```text
VR-0002: approved
manager: Priya Shah [SYNTHESIZED], Head of Operations, approved, 2026-10-09T14:50:00-07:00
```

If you edited the config, the digest shows your `company_name` and the manager line shows your `approvers.manager` string.

The sample decision time is 2026-10-09. A ticket created on a later day and closed at that time can show a negative days-open. The decision is still `approved`.

## Limits

- The Figma pack text was written for the Acme demo, so a few sentences in the pack still say Acme. Your company name is the one in the config. The digest is where you see it.
- This pilot does not send Slack or email.
- Do not pass `--live`. Dry run is the whole research step.
- The nudge timer is `stale_after_hours` from your config (48 in the sample, 20 in the Acme demo). Silence only nudges. It never counts as approval.
