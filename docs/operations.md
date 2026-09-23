# Operations

## Host Setup

Before anything else, follow `docs/host-setup.md` once on the HPZ440: GPU install, NVIDIA driver, NVIDIA Container Toolkit, and host directories.

## GPU Check

Run `pwsh -NoProfile -File scripts/check-gpu.ps1` to confirm the GPU is visible to containers on the remote host. It runs `nvidia-smi` inside a throwaway CUDA container and points to `docs/host-setup.md` on failure.

## Fetch a Model

Run `pwsh -NoProfile -File scripts/fetch-model.ps1` to download the default Qwen2.5-7B-Instruct Q4_K_M GGUF into `HOST_MODEL_DIR` on the host. Use `-Repo` and `-File` for a different single-file GGUF. See `docs/models.md`.

Then run `pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/<file>.gguf` to point `.env` at it.

## WebUI Secret

`scripts/start.ps1` refuses to start while `WEBUI_SECRET_KEY` in `.env` is missing or still `change-me-before-use`. Set it to a random string once; Open WebUI uses it to sign sessions. One way to generate a value in PowerShell:

```powershell
[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
```

`scripts/stop.ps1` never checks the secret, so a stack can always be stopped.

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

Benchmark JSON is written under `benchmarks/`, which is ignored by git. It includes `generated_tokens_per_second` and `prompt_tokens_per_second` from llama.cpp's `timings` block; record the generated figure in the Measured table in `docs/models.md`.

## Exposure

Public internet exposure is out of scope. Keep this service on the LAN unless a later hardening project adds authentication, TLS, and network controls.
