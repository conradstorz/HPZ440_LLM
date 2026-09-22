# Operations

## Start

Run `pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440` before starting.

Run `pwsh -NoProfile -File scripts/start.ps1` to start the stack.

## Stop

Run `pwsh -NoProfile -File scripts/stop.ps1`.

## Health

Run `pwsh -NoProfile -File scripts/health.ps1` to check `/v1/models` and Open WebUI.

## Switch Models

Run `pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/name.gguf`.

Restart the stack after switching models.

## Benchmark

Run `pwsh -NoProfile -File scripts/benchmark.ps1` after the API is healthy.

Benchmark JSON is written under `benchmarks/`, which is ignored by git.

## Exposure

Public internet exposure is out of scope. Keep this service on the LAN unless a later hardening project adds authentication, TLS, and network controls.
