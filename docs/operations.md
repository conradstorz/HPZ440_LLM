# Operations

## Host Setup

Before anything else, follow `docs/host-setup.md` once on the HPZ440: GPU install, NVIDIA driver, NVIDIA Container Toolkit, and host directories.

## GPU Check

Run `pwsh -NoProfile -File scripts/check-gpu.ps1` to confirm the GPU is visible to containers on the remote host. It runs `nvidia-smi` inside a throwaway CUDA container and points to `docs/host-setup.md` on failure.

## Fetch a Model

Run `pwsh -NoProfile -File scripts/fetch-model.ps1` to download the default Qwen2.5-7B-Instruct Q4_K_M GGUF into `HOST_MODEL_DIR` on the host. Use `-Repo` and `-File` for a different single-file GGUF (`-Subdir` for a subdirectory); a vision model needs a second call for its `mmproj` file. See `docs/models.md`.

Then add the model to `llama-swap/config.yaml` and re-run `scripts/start.ps1`: the config is baked into the `llm-api` image (a bind mount of a repo file would resolve on the remote host), so a change needs the rebuild.

## WebUI Secret

`scripts/start.ps1` refuses to start while `WEBUI_SECRET_KEY` in `.env` is missing or still `change-me-before-use`. Set it to a random string once; Open WebUI uses it to sign sessions. One way to generate a value in PowerShell:

```powershell
[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

`scripts/stop.ps1` never checks the secret, so a stack can always be stopped.

## Start

Run `pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440` before starting.

Run `pwsh -NoProfile -File scripts/start.ps1` to start the stack.

## Stop

Run `pwsh -NoProfile -File scripts/stop.ps1`.

## Workstation Access

`scripts/health.ps1` and `scripts/benchmark.ps1` call `http://localhost:<port>`, which assumes the HPZ440's published ports are forwarded to the workstation. Open a tunnel in a second terminal and leave it running:

```powershell
ssh -N -L 8080:localhost:8080 -L 3000:localhost:3000 -L 8090:localhost:8090 gte@hpz440
```

Adjust the ports if `.env` changes `LLM_HOST_PORT` or `WEBUI_HOST_PORT`. LAN clients reach the services directly at the HPZ440 hostname or IP instead.

## Health

Run `pwsh -NoProfile -File scripts/health.ps1` to check `/v1/models` (llama-swap lists every configured model, loaded or not) and Open WebUI. Neither this nor the `llm-api` container healthcheck loads a model.

## Switch Models

`llm-api` is llama-swap: every model in `llama-swap/config.yaml` is available on demand, selected by the request's `model` field, one loaded at a time. There is nothing to switch for ad-hoc use.

`pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath <id>` only changes which model id Jarvis and `benchmark.ps1` request (`LLM_MODEL_PATH`); `<id>` must be an id or alias in the config. Re-run `scripts/start.ps1` afterwards so Jarvis picks it up.

Model TTLs: the Qwen2.5-7B entry never unloads (Jarvis's scheduled runs need it); vision models unload after 300 s idle. Chatting with a vision model in Open WebUI evicts Qwen, and the next Jarvis request reloads it. If Open WebUI's Task Model (title/tag generation) is pinned to the Qwen model, every vision chat will swap Qwen in and out; see `docs/jarvis.md`.

## Benchmark

Run `pwsh -NoProfile -File scripts/benchmark.ps1` after the API is healthy.

Benchmark JSON is written under `benchmarks/`, which is ignored by git. It includes `generated_tokens_per_second` and `prompt_tokens_per_second` from llama.cpp's `timings` block; record the generated figure in the Measured table in `docs/models.md`.

### Concurrency sweep

`pwsh -NoProfile -File scripts/stress-test.ps1` is **disabled** since `llm-api` became llama-swap: the config
hard-codes `--parallel 1` and `--ctx-size 8192`, so `.env` no longer controls slots. The rest of this section
describes the original procedure, kept for the rework. The script measured aggregate throughput at 1, 2, 4, and
8 llama.cpp slots, holding 2048 tokens of context per slot. It rewrote `LLM_PARALLEL` and
`LLM_CONTEXT_SIZE` in `.env`, restarts `llm-api` once per slot count, and restores `.env`
byte-for-byte in a `finally` block. Jarvis shares `LLM_CONTEXT_SIZE`, so Jarvis is
unavailable for the few minutes the sweep runs. Unlike the other scripts it talks to
`http://hpz440:8080` directly rather than `localhost`, because an SSH tunnel would become the
bottleneck at eight concurrent streams.

## Exposure

Public internet exposure is out of scope. Keep this service on the LAN unless a later hardening project adds authentication, TLS, and network controls.
