# Data handling

The bot and the scripts never store bank account numbers, routing numbers, tax IDs (EIN/TIN), or SSNs in memory, in tickets, in packs, or in the audit log. If a requester sends one, intake rejects it and tells them to send only a reference such as `W-9 received`.

## What a pilot review may hold

A pilot review may hold a vendor name, a contact (the named business owner), the product, the use case, and review notes (the approver's words and any conditions).

Never give a request, a pack, a note, or the company config any of these:

- bank details (account numbers or routing numbers)
- EIN/tax IDs
- SSNs
- passwords
- contract PDFs
- customer data

A bank account number, routing number, EIN, TIN, or SSN is rejected and not written. That rejection is covered by `tests/test_sensitive.py`. `examples/company.sample.json` is included in the same scan, so the sample config never contains those values. The step-by-step pilot is [PILOT.md](PILOT.md).

## Approval notices

When a review reaches a human approval step, the request script can notify that role's approver from the company config by Slack and by email. Both channels are off unless the variables below are set. If a setting is unset, that channel is skipped and the skip is logged. A failed send does not stop or change the review.

A notice carries the vendor name, the decision needed, the review link, and the approver name and address (`approver_emails` in the company config). It never carries bank details, EIN/tax IDs, SSNs, passwords, or contract contents. Notices are not written to the ticket, the pack, or the audit log.

| Variable | Placeholder |
|---|---|
| `APPROVAL_SLACK_WEBHOOK_URL` | `https://hooks.slack.com/services/EXAMPLE/EXAMPLE/EXAMPLE` |
| `APPROVAL_SMTP_HOST` | `smtp.example.com` |
| `APPROVAL_SMTP_PORT` | `587` |
| `APPROVAL_SMTP_USER` | `notices@example.com` |
| `APPROVAL_SMTP_PASSWORD` | `replace-me` |
| `APPROVAL_SMTP_FROM` | `notices@example.com` |
| `APPROVAL_REVIEW_BASE_URL` | `https://reviews.example.com` |

Email stays off until host, port, user, password, and from are all set. The review link is the base URL plus the request id. These are placeholders. Do not commit a real webhook URL or password.

## Where data lives

The forking company is responsible for its own storage: where these folders sit, who can read them, and how they are backed up. This repo does not ship a database.

| Data | Where | Committed? |
|---|---|---|
| Company name, approvers, stale-after hours, data-sensitivity rule | `config/company.json` | Yes. The shipped file is demo data for Acme. |
| Example company config for a fork | `examples/company.sample.json` | Yes. Fictional company, synthesized people. Copy it over `config/company.json`. |
| Sample requests and sample packs | `data/samples/` | Yes. Public vendor facts, or synthesized people and messages. |
| Ticket (intake, route, decisions) | `tickets/<id>.json` | No |
| Research pack and fetch log | `packs/<id>/` | No |
| Audit log | `runs/<id>/audit.csv` | No |
| Other run files | `runs/` | No |

Generated tickets, packs, and runs are git-ignored. Do not commit them.

## Warranty

This software is provided as-is, with no warranty. See [LICENSE](LICENSE).
