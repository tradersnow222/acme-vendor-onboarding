# figma (VR-0002)

Expected end state:
- Route: manager
- Decision: approved
- Days open: 0.2

## Sub-features
- Intake check where all five fields arrive complete in the first message.
- Routing to the manager only, because Figma holds internal mockups with placeholder data.

## How to get to it (user POV)
A requester asks the bot for Figma for design mockups. The manager approves the same day with no conditions.

## Driving it with make run
Run `make run SAMPLE=figma`. The intake step reports complete and the routing step names only the manager.

## Gotchas
- The sample has no pack rows, so the pack check step has nothing to check.
- If a pack ever shows Acme customer data in R3, Security is added and the mismatch is flagged.
