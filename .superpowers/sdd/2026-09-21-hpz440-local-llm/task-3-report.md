# Task 3 Report

Status: DONE

Files changed:

- `scripts/check-context.ps1`
- `scripts/start.ps1`
- `scripts/stop.ps1`
- `tests/assert-script-contracts.ps1`

Validation:

```text
pwsh -NoProfile -File tests/assert-script-contracts.ps1
Script contract checks passed.

pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440
Docker context 'hpz440' is reachable.

git status --short
Untracked project files listed.
```

Concerns: none.

Self-review:

- Lifecycle scripts fail fast when `.env` is missing.
- `start.ps1` validates the remote Docker context before `compose up`.
- Compose commands run from the repository root so `.env` and `compose.yaml` resolve consistently.
