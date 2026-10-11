---
name: build-research-pack
description: Build a vendor research pack (rows R1 to R11) from public pages only, starting from templates/research_pack.json, until scripts/check_pack.py passes. Use when a vendor request needs its research pack.
---

# Build a research pack

Follow `.cursor/rules/research-checklist.mdc` and `.cursor/rules/data-boundaries.mdc`.

## Setup
1. Copy `templates/research_pack.json` to `packs/<request_id>/pack.json` and set `request_id`.
2. Write only under `packs/<request_id>/`. Never edit the template, samples, scripts, or rules.

## Where to look
Public pages only: pricing, trust or security, sub-processor list, DPA, main services agreement, data residency. Web search to find them is fine. No logins, gated portals, NDA documents, forms, or sales contact.

## Fetch log
Keep `packs/<request_id>/fetch_log.csv` with one line per fetch: `url,http_status,fetched_at` (time in ISO 8601). Every URL in a row's `source_urls` must appear in this log with HTTP 200.

## Filling rows
- Fill every row R1 to R11. A row may be split into sub-rows (R10a, R10b, ...) in the same format.
- Every row gets `source_urls` (a list, never empty) and `checked_date` as `YYYY-MM-DD`.
- `found`: `value` is the fact, and `source_urls` are the exact pages it came from.
- `not_found`: if a page can't be fetched or the fact isn't on it, set `value` to `"not found"` and list the URLs you checked. If it is only behind a login or NDA, say a person must request it.
- Never guess a URL. Only list URLs you actually fetched.
- `label` stays `PUBLIC` for facts read from a page.

## Must be found
R1, R3, R4, and R10 must be `found`. If any is not, stop and hand the pack to a person before routing. For R10, a "Talk to Sales" tier is fine if another tier is priced.

## R10 pilot cost
- Put the estimate in its own sub-row with `label` `ASSUMPTION` (the `[ASSUMPTION]` label in `data-boundaries.mdc`).
- Estimate = seats x monthly price x months. Use monthly prices; annual prices mean a 12-month commitment.
- If another row limits which tier is acceptable (e.g. data residency only on a higher tier), estimate with that tier.

## Cross-check
Compare intake `touches_customer_data` with R3. If they disagree, flag it (see `approval-policy.mdc`).

## Done
The pack is done when check_pack passes:

```
python3 -c "import json; from scripts.check_pack import check_pack; print(check_pack(json.load(open('packs/<request_id>/pack.json'))['rows'], 'packs/<request_id>/fetch_log.csv'))"
```

It must print `'passed': True` with no reasons. Fix every reason it lists, then run it again.
