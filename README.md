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

## Jarvis

Phase 1 of the Jarvis assistant runs as the `jarvis` service: read-only Gmail capture, local classification, evidence search, drafts, and a briefing page. Phase 1.5 adds chat: pick the **jarvis** model in Open WebUI and ask about your own mail. It answers from the archive with cited message keys, keeps the rules you teach it, and reads workstation documents on request. Setup and use: `docs/jarvis.md`.

```powershell
pwsh -NoProfile -File scripts/jarvis-auth.ps1   # once; reads C:\Users\<you>\.jarvis\credentials.json by default
pwsh -NoProfile -File scripts/jarvis-agent-token.ps1   # once, only for workstation documents; reads ~/.jarvis/agent_token
pwsh -NoProfile -File scripts/jarvis-run.ps1
pwsh -NoProfile -File scripts/jarvis-reindex.ps1
```

```powershell
pwsh -NoProfile -File scripts/stress-test.ps1   # concurrency sweep; rewrites and restores .env, Jarvis is down while it runs
```

See `docs/cost-model.md` for the concurrency sweep results and the hosted-vs-owned break-even comparison.

## Obi-Wan

Obi-Wan is the record keeper: it scans a read-only document corpus and an inbox, versions every file, and serves
full-text retrieval with provenance and coverage to Jarvis. Ask Jarvis about the documents in chat; confirm a fact it
relayed with your own credential. Setup and use: `docs/obiwan.md`.

```powershell
pwsh -NoProfile -File scripts/obiwan-seed-corpus.ps1 -SourceDir <folder>   # copy documents into the corpus on the host
pwsh -NoProfile -File scripts/obiwan-scan.ps1
pwsh -NoProfile -File scripts/obiwan-status.ps1
pwsh -NoProfile -File scripts/obiwan-confirm.ps1 -SubjectId <id>           # Commander only
pwsh -NoProfile -File scripts/obiwan-reindex.ps1
```

## Default URLs

- API: `http://localhost:8080/v1`
- Open WebUI: `http://localhost:3000`
- Jarvis briefing: `http://localhost:8090` (notes at `/notes`, chat API at `/v1/chat/completions`)
- Obi-Wan: `http://localhost:8070` (loopback on the HPZ440; tunnel required, bearer token required)

For LAN clients, replace `localhost` with the HPZ440 hostname or LAN IP.

From this workstation, the scripts expect an SSH tunnel; see the Workstation Access section in docs/operations.md.

## Roadmap

This stack is the inference layer of the Jarvis home assistant. See `docs/roadmap.md` for the phased plan and `docs/JARVIS_Home_Assistant_Reference.md` for the target design.
