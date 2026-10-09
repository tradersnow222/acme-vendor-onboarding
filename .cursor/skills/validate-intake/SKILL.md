---
name: validate-intake
description: Check a vendor request's five intake fields with scripts/intake_check.py and pick follow-up questions with scripts/followup.py. Use when a requester sends or answers a vendor request, before routing.
---

# Validate intake

Follow `.cursor/rules/intake-policy.mdc`. The script decides, not the bot.

## Steps
1. Extract the five fields into the shape in `intake-policy.mdc`: each field has `value`, `raw_text`, `from`, and `confirmed`.
2. Run the check. Never decide on your own that a field is fine.
3. Word only the questions the script picked, in one message.
4. After each reply, update the fields and run the check again.

## Commands
Run from the repo root. For a sample in `data/samples/`:

```
python3 -m scripts.intake_check <sample> --today <YYYY-MM-DD>
python3 -m scripts.followup <sample>
```

For a live conversation, save the fields as JSON and run:

```
python3 -m scripts.followup --fields <fields.json> --today <YYYY-MM-DD> --rounds <rounds_done>
```

## Rules
- At most 2 follow-up rounds. If the script marks an `exception`, hand the request to a person.
- Do not route until the check says `complete`.
- Never ask for a legal name that research can fill (`fill_from_research`).
