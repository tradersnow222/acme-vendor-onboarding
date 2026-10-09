---
name: verify-acme
description: Prove the Acme vendor-onboarding scripts work end to end from the command line, using the samples in data/samples/. Use after any change and before a demo.
---

# Verify Acme

Follow `.cursor/rules/verification.mdc`. Trust the real output, not a summary of it.
Per-sample expectations live in `.cursor/skills/verify-acme/features/README.md`.

## Launch
Nothing to start. Work from the repo root with no API key and a fresh scratch folder:

```
unset CURSOR_API_KEY
SCRATCH=$(mktemp -d) && export TMPDIR=$SCRATCH
```

## Doctor
- `python3 --version` prints 3.9 or newer.
- `python3 -c "from scripts.samples import list_samples; print(list_samples())"` prints `['zendesk', 'figma', 'asana']`.

If either fails, stop and fix the setup before driving anything.

## Drive
1. `make test` passes.
2. For each sample, run `python3 -m scripts.run <sample>` (the same as `make run SAMPLE=<sample>`).
3. Check that the approval commands start. This prints nothing when all pass:
   `for m in request_approvals record_approval ticket stale_check digest; do python3 -m scripts.$m --help >/dev/null || echo "FAIL $m"; done`

The step 2 trace comes from `scripts/run.py`. Each run exits 0 and prints 8 numbered steps.

## Evidence
Save each run under `runs/verify/` (git-ignored):

```
mkdir -p runs/verify
for s in zendesk figma asana; do python3 -m scripts.run $s > runs/verify/$s.txt; done
git status --short --ignored tickets runs
```

- Every line starts with its step number and one actor label: `[script]`, `[model]` or `[person]`.
- The dry run makes no network call. Tickets go to the scratch folder, not the repo.
- The `git status` line prints only `!! runs/verify/`. Anything else in `tickets/` or `runs/` is a failure.
- Compare each trace with its feature file and note any step that differs.

## Cleanup
- `rm -rf "$SCRATCH"` to remove the scratch folder you created.
- Keep `runs/verify/` so a reviewer can read the evidence.
