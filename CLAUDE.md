# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An operations repo plus the Jarvis Phase 1 application under `jarvis/`. It ships a Docker Compose stack (llama.cpp CUDA server + Open WebUI) that runs on the **remote** HPZ440 LAN server, plus PowerShell scripts that drive it from this Windows workstation via the Docker CLI context `hpz440`. Nothing runs locally except `uv run pytest` under `jarvis/` and the one-time OAuth consent in `scripts/jarvis-auth.ps1`.

This stack is the "local inference service" piece of the larger Jarvis home-assistant plan described in `docs/JARVIS_Home_Assistant_Reference.md`. The phased path from here to Jarvis is `docs/roadmap.md`; new work should map to a phase there. Phase 1 (Observe) and Phase 1.5 (Converse) are implemented under `jarvis/`; see `docs/jarvis.md`.

## Commands

```powershell
pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440   # verify remote docker context reachable
pwsh -NoProfile -File scripts/start.ps1                            # docker --context hpz440 compose up -d --build (runs check-context first; rebuilds jarvis when its source changed)
pwsh -NoProfile -File scripts/stop.ps1
pwsh -NoProfile -File scripts/health.ps1                           # GET /v1/models + WebUI root + jarvis /health
pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/name.gguf   # rewrites .env only; re-run start.ps1 to apply
pwsh -NoProfile -File scripts/benchmark.ps1 [-Prompt '...'] [-MaxTokens 64]  # writes benchmarks/benchmark-<stamp>.json
pwsh -NoProfile -File scripts/list-models.ps1                      # lists local models/*.gguf, not the remote dir
pwsh -NoProfile -File scripts/check-gpu.ps1                        # nvidia-smi in a throwaway container on hpz440
pwsh -NoProfile -File scripts/fetch-model.ps1 [-Repo r] [-File f]  # one-shot container downloads a GGUF into HOST_MODEL_DIR on the host
pwsh -NoProfile -File scripts/jarvis-auth.ps1 [-CredentialsPath p]   # one-time Gmail consent (default ~/.jarvis/credentials.json), copies token to host
pwsh -NoProfile -File scripts/jarvis-agent-token.ps1 [-TokenFile p]  # copies the GTE workspace agent token (default ~/.jarvis/agent_token) to /data/secrets/agent_token
pwsh -NoProfile -File scripts/jarvis-run.ps1                                        # POST /run then GET /health
pwsh -NoProfile -File scripts/jarvis-reindex.ps1                                    # rebuild FTS index in the container
```

Tests (each is a standalone script, no framework; run either individually):

```powershell
pwsh -NoProfile -File tests/assert-project-shape.ps1
pwsh -NoProfile -File tests/assert-script-contracts.ps1
```

Python: `cd jarvis` then `uv run pytest` (no network, no GPU).

## Architecture

- `compose.yaml` — `llm-api` (ghcr.io/ggml-org/llama.cpp:server-cuda, 1 NVIDIA GPU reserved) publishes `${LLM_HOST_PORT:-8080}`; `open-webui` talks to it over the compose network at `http://llm-api:8080/v1` and publishes `${WEBUI_HOST_PORT:-3000}`.
- Every tunable flows through `.env` (untracked, copied from `.env.example`). The compose file has defaults for each, but `start.ps1`/`stop.ps1` hard-require `.env` to exist, and `start.ps1` refuses to run while `WEBUI_SECRET_KEY` is missing or still `change-me-before-use`. `HOST_JARVIS_DATA_DIR` is bind-mounted at `/data` in the `jarvis` service.
- `start.ps1`/`stop.ps1` take the Docker context from `DOCKER_CONTEXT` in `.env` (falling back to `hpz440`), not from the CLI's currently selected context.
- Two path namespaces: `HOST_MODEL_DIR` (`/srv/llm/models` on the HPZ440) is bind-mounted read-only at `/models` in the container. `LLM_MODEL_PATH` must always be the **container** path (`/models/x.gguf`); `switch-model.ps1` enforces that regex.
- `jarvis` service builds from `jarvis/`, mounts `HOST_JARVIS_DATA_DIR` at `/data`, publishes `JARVIS_HOST_PORT`. Units import only `jarvis.core`, `jarvis.journal`, `jarvis.policy`; the pipeline wires them. Facts live in NKO v0 and are never rewritten; every later stage is a new version.
- The same service also serves `/v1/models` and `/v1/chat/completions` (`jarvis.openai_api` over `jarvis.agent`), which is how `open-webui` lists a `jarvis` model beside `llm-api` via `OPENAI_API_BASE_URLS`. Every model-requested tool call goes through `ToolRegistry.run`, which checks `policy` and writes a `tool_call` journal event; there is no other path. Teaching notes live in `/data/notes/notes.jsonl` and pending ones are injected nowhere.

## Conventions That Matter Here

- **Tests assert literal file content.** `tests/*.ps1` regex-match against `compose.yaml`, `.env.example`, `.gitignore`, `README.md`, `docs/*.md`, and each script. Renaming a script, changing a default port, or rewording a doc heading will break them — update the assertions in the same change. Only `assert-script-contracts.ps1` normalizes CRLF for multi-line patterns; `assert-project-shape.ps1` matches single lines.
- **`.env` parsing is duplicated** in `health.ps1` and `benchmark.ps1` (identical `Get-Content | -match '^[A-Z0-9_]+=.*$'` block); `start.ps1`, `stop.ps1`, `list-models.ps1`, `check-gpu.ps1`, `fetch-model.ps1`, `jarvis-auth.ps1`, `jarvis-run.ps1`, `jarvis-reindex.ps1`, and `jarvis-agent-token.ps1` use `Select-String` on single keys instead. Keep any parsing change consistent across all eleven.
- Scripts target `http://localhost:<port>`, which assumes the workstation reaches the HPZ440's published ports at localhost (SSH tunnel or equivalent). LAN clients use the hostname/IP instead.
- `list-models.ps1` prints `HOST_MODEL_DIR` but only enumerates the local `models/` directory — it does not list files on the remote host.
- Model weights, `.env`, `benchmarks/`, and logs are gitignored. Keep it that way.

## Scope

Public internet exposure is explicitly out of scope (see `docs/operations.md`). No auth or TLS; LAN only. Default profile targets 7B instruct GGUF at Q4_K_M/Q5_K_M for the RTX 3060 12GB.

Design spec and plan live in `docs/superpowers/`; per-task implementation reports in `.superpowers/sdd/`.
