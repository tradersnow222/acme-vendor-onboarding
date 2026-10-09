# zendesk (VR-0001)

Expected end state:
- Route: manager, security
- Decision: approved_with_conditions
- Days open: 1.1

## Sub-features
- Intake check that asks for the start date, confirms two hedged answers, and fills the legal name from research.
- Research pack check on a full pack with two `not_found` rows.
- Routing to Security as well as the manager, because Zendesk would hold Acme customer data.

## How to get to it (user POV)
A requester asks the bot for a Zendesk support pilot. After one follow-up round the request is routed. The manager approves first. Security stays silent, gets one nudge, then approves with conditions.

## Driving it with make run
Run `make run SAMPLE=zendesk`. The pack check step reports the 14 sample rows and the routing step names both approvers.

## Gotchas
- This is the only sample with pack rows, so it is the only one where the pack check really runs.
- Security silence is not a yes. The nudge is logged but does not count as an exception.
