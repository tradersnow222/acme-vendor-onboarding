# verify-acme feature map

One file per sample in `data/samples/`. Each file says how to reach the sample, how to drive it, and the end state it should reach.

| Sample | File | Route | Decision | Days open |
|---|---|---|---|---|
| zendesk | [zendesk.md](zendesk.md) | manager, security | approved_with_conditions | 1.1 |
| figma | [figma.md](figma.md) | manager | approved | 0.2 |
| asana | [asana.md](asana.md) | manager | approved | 0.9 |
