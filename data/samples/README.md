# Sample requests

Three vendor requests that the scripts (intake check, research pack, routing, status, audit) must handle. Each file is plain JSON, so Python's standard `json` module can read it. Each one also works as a pass/fail test case.

Vendors are real public companies. Every Acme person, message, time, and approver reply is made up and labeled **[SYNTHESIZED]**. Acme is fictional.

| File | Vendor | Case | Expected outcome |
|---|---|---|---|
| `vr-0001-zendesk.json` | Zendesk, Inc. | Worked example (hand-run on Oct 8, 2026) | Intake asks for a start date and confirms the customer-data answer (1 round). Customer data yes, so the route is **manager + Security**. Ends **approved with conditions**, about 1.1 days open, 3 exceptions. |
| `vr-0002-figma.json` | Figma, Inc. | Clean request, no customer data | All five fields in the first message, **0 follow-up rounds**. Route is **manager only**. Ends **approved**, about 0.2 days open. |
| `vr-0003-asana.json` | Asana, Inc. | Exception: business owner left out | Intake asks **only for the business owner** (round 1 of max 2), and routing is blocked until it's filled. Route is **manager only**. Ends **approved**, about 0.9 days open. |
| `vr-0001-zendesk-audit.csv` | Zendesk, Inc. | Expected audit log from the hand-run | 18 rows: 10 script, 4 model, 4 person. |

## What's in each file
- `people`: requester, manager, and Security reviewer (only when needed).
- `messages`: the conversation in order. `round` 0 is the first request; round 1 is the bot's follow-up and the reply.
- `approver_replies`: scripted approver decisions that stand in for real people in the demo (mocked input).
- `expected`: what the scripts should produce.
  - `intake`: which fields to ask for, confirm, or fill from research after the first message; rounds used; the final five fields, each with `value`, `raw_text`, `from` (requester or research), and `confirmed`.
  - `pack`: for Zendesk, the full hand-run pack (rows R1 to R11, each with `source_urls`, `checked_date`, and `status` = found or not_found). For Figma and Asana, `rows` is `null` because the research step builds those packs later.
  - `routing`: who must approve and why.
  - `status`: final decision, named approvers and times, days open, and exceptions.

## Notes
- Days open runs from the first requester message to the last required named approval.
- Exceptions = missing intake fields + "not found" pack rows + rejections. For Figma and Asana, `not_found_pack_rows` and `total` are `null` until their packs exist.
- The Zendesk pack has 14 rows (12 found, 2 not found). The hand-run notes say "13 of 15 rows", which is a counting slip; the rows themselves are unchanged.
