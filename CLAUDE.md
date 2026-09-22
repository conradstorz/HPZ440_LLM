# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An operations repo — no application code. It ships a Docker Compose stack (llama.cpp CUDA server + Open WebUI) that runs on the **remote** HPZ440 LAN server, plus PowerShell scripts that drive it from this Windows workstation via the Docker CLI context `hpz440`. Nothing runs locally.

## Commands

```powershell
pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440   # verify remote docker context reachable
pwsh -NoProfile -File scripts/start.ps1                            # docker --context hpz440 compose up -d
pwsh -NoProfile -File scripts/stop.ps1
pwsh -NoProfile -File scripts/health.ps1                           # GET /v1/models + WebUI root
pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/name.gguf
pwsh -NoProfile -File scripts/benchmark.ps1                        # writes benchmarks/benchmark-<stamp>.json
```

Tests (each is a standalone script, no framework; run either individually):

```powershell
pwsh -NoProfile -File tests/assert-project-shape.ps1
pwsh -NoProfile -File tests/assert-script-contracts.ps1
```

## Architecture

- `compose.yaml` — `llm-api` (ghcr.io/ggml-org/llama.cpp:server-cuda, 1 NVIDIA GPU reserved) publishes `${LLM_HOST_PORT:-8080}`; `open-webui` talks to it over the compose network at `http://llm-api:8080/v1` and publishes `${WEBUI_HOST_PORT:-3000}`.
- Every tunable flows through `.env` (untracked, copied from `.env.example`). The compose file has defaults for each, but `start.ps1`/`stop.ps1` hard-require `.env` to exist.
- Two path namespaces: `HOST_MODEL_DIR` (`/srv/llm/models` on the HPZ440) is bind-mounted read-only at `/models` in the container. `LLM_MODEL_PATH` must always be the **container** path (`/models/x.gguf`); `switch-model.ps1` enforces that regex.

## Conventions That Matter Here

- **Tests assert literal file content.** `tests/*.ps1` regex-match against `compose.yaml`, `.env.example`, `.gitignore`, `README.md`, `docs/*.md`, and each script. Renaming a script, changing a default port, or rewording a doc heading will break them — update the assertions in the same change.
- **`.env` parsing is duplicated** in `health.ps1` and `benchmark.ps1` (identical `Get-Content | -match '^[A-Z0-9_]+=.*$'` block); `start.ps1`, `stop.ps1`, and `list-models.ps1` use `Select-String` on a single key instead. Keep any parsing change consistent across all five.
- Scripts target `http://localhost:<port>`, which assumes the workstation reaches the HPZ440's published ports at localhost (SSH tunnel or equivalent). LAN clients use the hostname/IP instead.
- `list-models.ps1` prints `HOST_MODEL_DIR` but only enumerates the local `models/` directory — it does not list files on the remote host.
- Model weights, `.env`, `benchmarks/`, and logs are gitignored. Keep it that way.

## Scope

Public internet exposure is explicitly out of scope (see `docs/operations.md`). No auth or TLS; LAN only. Default profile targets 7B instruct GGUF at Q4_K_M/Q5_K_M for the RTX 3060 12GB.

Design spec and plan live in `docs/superpowers/`; per-task implementation reports in `.superpowers/sdd/`.
