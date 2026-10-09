# Acme Vendor Onboarding Automation

A governed workflow for vendor onboarding at Acme, Inc.: intake → research pack → approval routing. Built with Grok Bot and Grok Build (Cursor), using public and synthesized data only.

---

## The Problem

**Maya Chen (Staff Ops, Acme)** owns the vendor onboarding process, which today takes 1-2 weeks due to manual handoffs and unclear approval flows. Leadership wants this down to 1-2 days with a clear audit trail.

### Current Process: Intake → Research → Approval Routing

When someone wants to pilot a vendor, the process has three stages but four key frictions:

#### 1. **Intake is messy**
- Requesters email or open a ticket: "Onboard Vendor X for a 90-day pilot"
- Required fields are often incomplete:
  - Vendor legal name
  - Website
  - Whether they will touch customer data
  - Business owner
  - Target start date
- Ops chases missing fields over email, adding days of back-and-forth

#### 2. **Research is manual copy/paste**
- Ops manually gathers public vendor info (website, security/trust page, public pricing) into a shared doc
- No standard pack template exists
- No checklist defines what "enough research" means
- Each pack is inconsistent and time-consuming to build

#### 3. **Approvals are late and unclear**
- A manager reviews whenever they notice the thread (no proactive routing)
- Security is pinged late, and only if the vendor touches customer data
- No single status view exists
- No audit trail shows what was checked or who approved what

#### 4. **Cycle time is too long**
- End-to-end typically takes **1-2 weeks** of handoffs
- Leadership wants **1-2 days** with clear records of checks and approvals

---

## The Solution: Governed Workflow with Bot + Build

### Planned Flow

1. **Grok Bot is the front door**
   - Requester starts by messaging the Acme bot
   - Bot collects the five required fields, asking only for missing ones (max two rounds)
   - Anyone can ask for status without hunting through email

2. **Cursor holds the durable structure**
   - **Rules** (`.cursor/rules/`): `data-boundaries`, `intake-policy`, `research-checklist`, `approval-policy`, `status-and-audit`, `git-workflow` (includes commit hygiene)
   - **Skills**: `validate-intake`, `build-research-pack`
   - **Scripts**: Field check, routing logic, audit log (with cost tracking), status generator, Cursor API launcher

3. **Cloud agent builds the research pack**
   - Bot writes a research brief and starts a Cursor cloud agent via the Cursor API
   - Agent gathers public info (website, trust page, pricing) using the research checklist
   - Every item includes a source link or "not found" label
   - Completed pack alerts the requester and manager

4. **Approval routing is code-driven**
   - **Manager approval**: Always required, routed automatically
   - **Security approval**: Required when vendor will touch customer data
   - **Named person only**: Silence never counts as approval
   - Plain-English review summarizes the pack and flags any "not found" items

5. **Audit trail and status**
   - Every step writes an audit log row: who, when, what they saw, cost
   - Status file shows days open per request, exception count (missing fields, "not found" items, rejections), and whether each step was script/model/person
   - Approved requests show approver name and timestamp

### Human-in-the-Loop Guardrails

- **Manager** approves every vendor
- **Security** approves when customer data is involved
- **Requester** can steer: change fields or re-run research
- **Ops** sees daily digest: open requests, days open, exceptions, automated vs. needed-a-person
- **No auto-approval**: The bot cannot approve, send email, or touch private data

---

## How to Run

You need Python 3.9 or newer. There is nothing to pip install. Run every command from the repo root.

### 1. Set up

```bash
make setup
```

You should see `✓ Project structure ready`.

### 2. Test

```bash
make test
```

Without make, run `python3 -m unittest discover -s tests -v`. The last line should be `OK`.

### 3. Trace one sample with one command

```bash
make run SAMPLE=zendesk
make run SAMPLE=figma
make run SAMPLE=asana
```

Each step prints one numbered line, labeled `[script]`, `[model]`, or `[person]` for who does that step.

- `zendesk` is the worked example: one follow-up round, then routed to the manager plus Security.
- `figma` is a clean request: no follow-ups, routed to the manager only.
- `asana` is the exception: the business owner is missing, so it is chased in round 1.

`make run` is always a dry run: no network and no key. Its ticket and audit files go to temp folders, printed in steps 3 and 8.

### 4. Step by step on one request

These commands write to `tickets/`, `packs/`, and `runs/`, which git ignores.

```bash
python3 -m scripts.ticket zendesk
python3 -m scripts.launch_research --ticket VR-0001
python3 -m scripts.fetch_pack --ticket VR-0001 --reply-file <saved reply>
python3 -m scripts.status --ticket VR-0001
```

1. `scripts.ticket` writes `tickets/VR-0001.json`.
2. `scripts.launch_research` prints the Cursor API request it would send (dry run).
3. `scripts.fetch_pack` pulls the pack out of the research agent's final reply into `packs/VR-0001/`. It writes the pack back to the ticket only if the pack check passes.
4. `scripts.status` prints the status from the ticket and `runs/VR-0001/audit.csv`.

### Dry run vs live

Dry run is the default everywhere. `--live` is the only way to spend money. The key comes only from the `CURSOR_API_KEY` environment variable, never from a file or a flag.

```bash
python3 -m scripts.launch_research --ticket VR-0001 --live
python3 -m scripts.fetch_pack --ticket VR-0001 --live
```

Run `launch_research --live`, wait for the agent, then run `fetch_pack --live`. If `fetch_pack` exits with code 3, the agent is still running; run it again later.

### Other make targets

```bash
make validate SAMPLE=<name>
make route SAMPLE=<name>
make research TICKET=<id>
make status TICKET=<id>
make audit TICKET=<id>
make clean
```

### Folder layout

```
acme-vendor-onboarding/
├── scripts/          # Python scripts (intake check, follow-up, ticket, routing, approvals, audit, status, Cursor API)
├── tests/            # Unit tests run by make test
├── data/samples/     # Sample vendor requests (synthesized) with expected outputs
├── templates/        # Research pack template
├── config/           # Approval settings (nudge after N hours)
├── tickets/          # One ticket file per request (output, git-ignored)
├── packs/            # Research packs (output, git-ignored)
├── runs/             # Audit logs and agent run files (output, git-ignored)
├── .cursor/rules/    # Cursor rules (data boundaries, intake, research checklist, approval, status/audit, git)
├── .cursor/skills/   # Skills (validate-intake, build-research-pack)
├── Makefile          # make setup, test, run, and the targets above
└── README.md         # This file
```

---

## What's Live, Mocked, or Synthesized

| Component               | Status      | Notes                                                                 |
|------------------------|-------------|-----------------------------------------------------------------------|
| Grok Bot intake         | Live        | The Acme Vendors bot; `make run` replays the sample messages instead  |
| Field validation        | Live        | Script, runs locally                                                  |
| Follow-up picker        | Live        | Script, runs locally                                                  |
| Research pack template  | Live        | `templates/research_pack.json`                                        |
| Pack checker            | Live        | Script, runs locally                                                  |
| Cloud agent (via API)   | Live        | Cursor API call with `--live`; dry run by default                     |
| Public data sources     | Live        | Real vendor websites, trust pages, pricing (public only)              |
| Sample requesters       | Synthesized | Fictional Acme requesters, managers, approvers, labeled [SYNTHESIZED] in `data/samples/` |
| Sample vendors          | Mixed       | Real public companies (Zendesk, Figma, Asana); pilot details synthesized |
| Zendesk research pack   | Public      | Hand-run from public vendor pages on Oct 8, 2026; kept as the expected pack in `data/samples/` |
| Approval routing        | Live        | Script, runs locally                                                  |
| Approval recorder       | Live        | Script, runs locally                                                  |
| Audit log               | Live        | Script, runs locally                                                  |
| Status generator        | Live        | Script, runs locally                                                  |
| Manager approvals       | Mocked      | Pre-set `approver_replies` in `data/samples/`; real humans in production |
| Security approvals      | Mocked      | Pre-set `approver_replies` in `data/samples/`; real Security team in production |

---

## Assumptions

These assumptions are baked into the current design and should be validated with Maya:

1. **Public research is enough for pilot decisions**
   - The research pack uses only public sources (website, trust page, pricing)
   - Private security assessments or detailed compliance docs are not part of this automated flow

2. **Five fields are sufficient for intake**
   - Vendor legal name, website, customer data flag, business owner, target start date
   - Other fields (budget, contract term, renewal terms) are handled separately

3. **Manager approval is always required**
   - Every vendor, regardless of size or risk, needs manager sign-off
   - No auto-approval for low-risk or repeat vendors

4. **Security approval threshold is binary**
   - "Will this vendor touch customer data?" is a yes/no question
   - More granular risk tiers (PII, financial data, logs) are not distinguished in this flow

5. **Approval must be explicit**
   - Silence never counts as approval
   - Approvers must respond with a named decision

6. **Cycle time is measured in days**
   - "Days open" is the key metric
   - Hour-level or minute-level SLAs are not tracked

7. **Status visibility is self-service**
   - Requesters and approvers can ask the bot for status anytime
   - No email notifications or dashboard required for this version

8. **One request per vendor at a time**
   - The system does not handle multiple concurrent pilots for the same vendor
   - Duplicate detection or conflict resolution is out of scope

9. **Audit log captures cost**
   - Each step logs the cost of API calls and model usage
   - Cost tracking supports future optimization and budget accountability

10. **The bot does not send email**
    - All communication happens within the bot interface
    - Email integration is intentionally excluded to avoid expanding the scope

---

## Questions for Maya

Before finalizing the design and building the full workflow, we should clarify:

1. **Research scope**
   - Is public information (website, trust page, pricing) sufficient for pilot approval decisions?
   - Are there specific sections or details we should always look for on a trust page (e.g., SOC 2, ISO 27001, data residency)?
   - What should we do if a vendor has no public trust page or pricing?

2. **Approval routing**
   - Is "touches customer data" the right trigger for Security involvement, or are there other risk factors (PII, financial data, API access)?
   - Should Finance or Legal ever be in the approval path, or is it always Manager + Security (conditional)?
   - Can a manager delegate approval authority to another person, or must it be the named manager?

3. **Exception handling**
   - If a vendor is missing critical public info (e.g., no trust page), does the request automatically get escalated, or does the manager decide?
   - What happens if an approver rejects a request — does it go back to the requester, or is it closed immediately?
   - Should the bot nudge stale approvals, and if so, how often (daily? every 2 days?)?

4. **Status and reporting**
   - Who needs to see the daily Ops digest (just Ops, or also managers)?
   - Are "days open" and "exception count" the right metrics, or should we track something else (e.g., requests approved per week)?
   - Should status show requester name and business owner, or is that too detailed for a summary view?

5. **Data and vendors**
   - Do you have a list of pre-approved vendors (e.g., major SaaS tools) that could skip some research, or does every vendor go through the full flow?
   - Should we track repeat vendors (same vendor, different pilot or renewal), or treat each request as independent?

6. **Bot interaction**
   - Should the bot confirm the research pack with the requester before sending it to approvers, or send it directly?
   - Can a requester update fields (e.g., change the business owner) after the pack is built, or must they start a new request?

7. **Audit and compliance**
   - Who needs access to the audit log, and in what format (CSV, dashboard, API)?
   - How long should audit records be retained (90 days, 1 year, indefinitely)?

8. **Pilot vs. production vendor onboarding**
   - Is this workflow only for pilots, or should it eventually handle full production vendor onboarding?
   - Are there different approval requirements for pilots vs. production?

---

## Owners (Proposed)

Each component of this solution has a proposed owner at Acme. These are recommendations based on typical responsibilities and should be validated with leadership.

| Component                     | Proposed Owner  | Rationale                                                                 |
|------------------------------|----------------|---------------------------------------------------------------------------|
| **Grok Bot (front door)**     | Ops            | Ops owns vendor onboarding and is the primary user; they steer the bot    |
| **Intake validation script**  | Ops            | Business logic for required fields; Ops knows what's needed               |
| **Research pack template**    | Ops            | Defines what "enough research" means; Ops reviews the packs               |
| **Cloud agent orchestration** | Engineering    | Cursor API integration and agent config; technical ownership              |
| **Approval routing logic**    | Ops            | Business rules for manager/Security routing; Ops owns the process         |
| **Security approval rules**   | Security       | Defines when Security must approve and what they review                   |
| **Audit log and compliance**  | Security       | Audit trail and data boundaries are security concerns                     |
| **Status and reporting**      | Ops            | Ops needs visibility into cycle time, exceptions, and workload            |
| **Cursor rules (data, git)**  | Engineering    | Technical guardrails and development workflow                             |
| **Cost tracking**             | Engineering    | API usage and model cost are engineering metrics                          |
| **Bot skills and tools**      | Engineering    | Bot capabilities and integrations are engineering work                    |

### Ownership Notes

- **Ops** is the primary business owner and the main user of the system. They define what "done" looks like, what research is sufficient, and how approvals should flow.
- **Security** defines the approval policy for customer data and owns the audit trail. They should review the data boundaries and approval logic.
- **Engineering** builds and maintains the technical components (scripts, Cursor API integration, bot tools) and ensures the system is reliable and cost-effective.

### Cross-functional collaboration points

- **Ops + Security**: Agree on when Security approval is required and what they review
- **Ops + Engineering**: Define the research checklist and translate it into bot/agent logic
- **Security + Engineering**: Validate data boundaries and audit logging
- **All three**: Review cycle time metrics, exceptions, and cost to ensure the workflow meets goals

---

## Stack and Structure

**Language**: Python 3 (standard library only, no external dependencies)

**Why Python 3 standard library**:
- Minimal dependencies: No need for pip installs, virtual environments, or version conflicts
- Simple to run: Scripts execute directly with `python3 script.py`
- Easy to read: Standard library modules (json, csv, datetime, pathlib) are widely known
- Fast to iterate: No build step, no package management, just code and run

**Project Layout**:
```
acme-vendor-onboarding/
├── scripts/          # Python scripts (validation, routing, audit, status)
├── data/samples/     # Sample vendor requests (synthesized data)
├── packs/            # Generated research packs (output, not committed)
├── runs/             # Cloud agent run logs (output, not committed)
├── .cursor/rules/    # Cursor rules (data boundaries, intake, research checklist, approval, status/audit, git)
├── .gitignore        # Ignore packs/, runs/, Python cache
├── AGENTS.md         # Agent guidelines (git workflow, data boundaries)
├── README.md         # This file
└── Makefile          # (Planned) Simple commands to run validation, routing, status
```

---

## Development Workflow

See `.cursor/rules/git-workflow.mdc` and `AGENTS.md` for full details.

**Summary**:
- Work on a new branch for every change
- Open a pull request for Matt to review
- Never commit or push directly to `main`
- Never merge your own pull request
- Never force-push
- Write small, focused commits with clear messages explaining **why**

---

## License

Internal Acme project. Not open source.
