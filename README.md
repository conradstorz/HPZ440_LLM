# HPZ440 Local LLM

Operations project for serving 7B-class GGUF models from the HPZ440 LAN server with an RTX 3060 12GB GPU.

## What It Runs

- `llama.cpp` server for an OpenAI-compatible API.
- Open WebUI for browser chat.
- PowerShell scripts for lifecycle, health checks, model switching, and small benchmarks.

## Quickstart

1. Put a 7B GGUF model on the HPZ440 under `/srv/llm/models`.
2. Copy `.env.example` to `.env`.
3. Set `LLM_MODEL_PATH=/models/<model>.gguf` in `.env`.
4. Run `pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440`.
5. Run `pwsh -NoProfile -File scripts/start.ps1`.
6. Run `pwsh -NoProfile -File scripts/health.ps1`.

## Default URLs

- API: `http://localhost:8080/v1`
- Open WebUI: `http://localhost:3000`

For LAN clients, replace `localhost` with the HPZ440 hostname or LAN IP.

## Roadmap

This stack is the inference layer of the Jarvis home assistant. See `docs/roadmap.md` for the phased plan and `docs/JARVIS_Home_Assistant_Reference.md` for the target design.
