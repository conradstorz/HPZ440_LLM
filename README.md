# HPZ440 Local LLM

Operations project for serving 7B-class GGUF models from the HPZ440 LAN server with an RTX 3060 12GB GPU.

## What It Runs

- `llama.cpp` server for an OpenAI-compatible API.
- Open WebUI for browser chat.
- PowerShell scripts for lifecycle, health checks, model switching, and small benchmarks.

## Quickstart

1. On the HPZ440, follow `docs/host-setup.md` once (GPU, driver, NVIDIA Container Toolkit, host directories).
2. Run `pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440`.
3. Run `pwsh -NoProfile -File scripts/check-gpu.ps1`.
4. Copy `.env.example` to `.env` and set `WEBUI_SECRET_KEY` to a random value.
5. Run `pwsh -NoProfile -File scripts/fetch-model.ps1` to download the default model to the host.
6. Run `pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/Qwen2.5-7B-Instruct-Q4_K_M.gguf`.
7. Run `pwsh -NoProfile -File scripts/start.ps1`.
8. Run `pwsh -NoProfile -File scripts/health.ps1`.
9. Run `pwsh -NoProfile -File scripts/benchmark.ps1` and record the result in `docs/models.md`.

## Default URLs

- API: `http://localhost:8080/v1`
- Open WebUI: `http://localhost:3000`

For LAN clients, replace `localhost` with the HPZ440 hostname or LAN IP.

## Roadmap

This stack is the inference layer of the Jarvis home assistant. See `docs/roadmap.md` for the phased plan and `docs/JARVIS_Home_Assistant_Reference.md` for the target design.
