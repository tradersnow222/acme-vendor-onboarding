# Data handling

The bot and the scripts never store bank account numbers, routing numbers, tax IDs (EIN/TIN), or SSNs in memory, in tickets, in packs, or in the audit log. If a requester sends one, intake rejects it and tells them to send only a reference such as `W-9 received`.

## Where data lives

The forking company is responsible for its own storage: where these folders sit, who can read them, and how they are backed up. This repo does not ship a database.

| Data | Where | Committed? |
|---|---|---|
| Company name, approvers, stale-after hours, data-sensitivity rule | `config/company.json` | Yes. The shipped file is demo data for Acme. |
| Sample requests and sample packs | `data/samples/` | Yes. Public vendor facts, or synthesized people and messages. |
| Ticket (intake, route, decisions) | `tickets/<id>.json` | No |
| Research pack and fetch log | `packs/<id>/` | No |
| Audit log | `runs/<id>/audit.csv` | No |
| Other run files | `runs/` | No |

Generated tickets, packs, and runs are git-ignored. Do not commit them.

## Warranty

This software is provided as-is, with no warranty. See [LICENSE](LICENSE).
