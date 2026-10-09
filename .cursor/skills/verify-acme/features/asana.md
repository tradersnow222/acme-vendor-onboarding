# asana (VR-0003)

Expected end state:
- Route: manager
- Decision: approved
- Days open: 0.9
- Exception: the missing business owner

## Sub-features
- Intake check where the business owner is missing at first and filled after one follow-up round.
- Routing to the manager only, because Asana holds internal tasks and timelines.

## How to get to it (user POV)
A requester asks the bot for Asana without naming a business owner. The bot asks once, the requester names one, and the manager approves the next morning.

## Driving it with make run
Run `make run SAMPLE=asana`. The intake step reports complete because the trace uses the fields after the reply, and the routing step names only the manager.

## Gotchas
- The missing business owner counts as one exception even though the trace shows intake complete.
- Routing is blocked until the business owner is filled.
- The sample has no pack rows, so the pack check step has nothing to check.
