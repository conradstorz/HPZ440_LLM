# Phase 0: Foundation Design

Status: Approved
Updated: 2026-09-23
Roadmap phase: `docs/roadmap.md`, Phase 0

## Purpose

Turn the existing, never-run inference stack into a working, measured inference layer on real hardware, and add the small configuration surface that Phase 1 (the Jarvis read-only briefing) will need. No Jarvis application code, mail access, or cloud calls.

## Facts established

- HPZ440 runs Ubuntu 24.04.4 LTS, kernel 6.8, Docker Engine 28.3.3, Docker Compose v5.3.0, reached through the Docker CLI context `hpz440`.
- The Docker daemon currently lists only the `runc` runtime. The NVIDIA Container Toolkit is not installed.
- The RTX 3060 12GB is not yet physically installed.
- First model: Qwen2.5-7B-Instruct, Q4_K_M, as a single GGUF file. Qwen's official GGUF repository splits that quantization into two files, so the default source is bartowski's single-file build.

## Deliverables

### 1. Host setup documentation (`docs/host-setup.md`)

Manual steps run over SSH on the HPZ440 as a sudo user. Not scripted: they need sudo, a reboot, and human judgement about driver versions.

Sections, in order:

1. Physical install and BIOS check (card seated, power connected, `lspci | grep -i nvidia` shows the device).
2. NVIDIA driver: `sudo ubuntu-drivers install`, reboot, `nvidia-smi` shows the RTX 3060.
3. NVIDIA Container Toolkit: add NVIDIA's apt repository, `sudo apt install nvidia-container-toolkit`, `sudo nvidia-ctk runtime configure --runtime=docker`, `sudo systemctl restart docker`.
4. Verify from the workstation with `scripts/check-gpu.ps1` (deliverable 2).
5. Create `HOST_MODEL_DIR` and `HOST_JARVIS_DATA_DIR` on the host (`sudo mkdir -p /srv/llm/models /srv/llm/jarvis-data`, owned by the SSH user) so bind mounts and the fetch script have writable targets.

The doc states the NVIDIA apt repository setup commands verbatim from NVIDIA's installation guide for Ubuntu and names the guide URL so the operator can check for changes.

### 2. `scripts/check-gpu.ps1`

Operator preflight that proves the GPU is visible to containers on the remote host.

- Parameters: `-Context` (default: `DOCKER_CONTEXT` from `.env` if present, else `hpz440`), following the `Select-String` single-key convention used by `start.ps1`.
- Runs `docker --context <ctx> run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu24.04 nvidia-smi`.
- Prints the `nvidia-smi` output on success. On failure, throws a message that names the two usual causes: NVIDIA Container Toolkit not installed or Docker not restarted after `nvidia-ctk runtime configure`, and points to `docs/host-setup.md`.
- `start.ps1` does not call it. It is a documented preflight, like `check-context.ps1`.

### 3. `scripts/fetch-model.ps1`

Downloads one GGUF file from Hugging Face directly into `HOST_MODEL_DIR` on the HPZ440.

- Parameters: `-Repo` (default `bartowski/Qwen2.5-7B-Instruct-GGUF`), `-File` (default `Qwen2.5-7B-Instruct-Q4_K_M.gguf`), `-Context` (same resolution as `check-gpu.ps1`).
- Reads `HOST_MODEL_DIR` from `.env` with `Select-String` (default `/srv/llm/models`). Requires `.env` to exist, with the same error message style as the other scripts.
- Runs a one-shot container: `docker --context <ctx> run --rm -v <HOST_MODEL_DIR>:/models python:3.12-slim sh -c "pip install --quiet huggingface_hub && hf download <Repo> <File> --local-dir /models"`.
- If the target file already exists in the mount, the container command skips the download and says so. Implement by checking `test -f /models/<File>` inside the same `sh -c` before installing anything.
- On success prints the exact follow-up command: `pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/<File>`.
- Gated repositories (Llama, Gemma) are out of scope: the doc says to download them manually with an authenticated `hf` CLI on the host and copy into `HOST_MODEL_DIR`.
- The `models/` directory in this repo remains a placeholder; nothing is downloaded to the workstation.

### 4. `scripts/benchmark.ps1` throughput fields

llama.cpp's OpenAI-compatible chat completion response includes a `timings` object with `prompt_n`, `prompt_ms`, `prompt_per_second`, `predicted_n`, `predicted_ms`, `predicted_per_second`, plus the standard `usage` object.

Add these top-level fields to the benchmark JSON, keeping every existing field and the `benchmarks/benchmark-<stamp>.json` path:

| Field | Source |
| --- | --- |
| `prompt_tokens` | `timings.prompt_n` |
| `prompt_tokens_per_second` | `timings.prompt_per_second` |
| `generated_tokens` | `timings.predicted_n` |
| `generated_tokens_per_second` | `timings.predicted_per_second` |
| `usage` | `usage` |
| `model` | `.env` `LLM_MODEL_PATH` at the time of the run |

If `timings` is absent from the response (a different backend, or a future llama.cpp change), the four throughput fields are written as `null` and the script still succeeds. The console line gains generated tokens per second when available.

### 5. Configuration and guards

- `.env.example` adds `HOST_JARVIS_DATA_DIR=/srv/llm/jarvis-data` under a comment noting it is reserved for Phase 1. `compose.yaml` is not changed: a bind mount needs a consuming service, and that service arrives in Phase 1.
- `.gitignore` adds `jarvis-data/` under "Runtime data".
- `start.ps1` reads `WEBUI_SECRET_KEY` with `Select-String` and throws if it is missing or equals `change-me-before-use`. The error tells the operator to set a random value and gives one way to generate it in PowerShell (`[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))`, or equivalent).
- `stop.ps1` is unchanged; stopping a stack with a weak secret must always work.

### 6. Documentation

- `docs/models.md`: keep existing guidance; add a "Measured" table with columns Model, Quantization, Context, Generated tok/s, Date, Notes. Ship it with one row for Qwen2.5-7B-Instruct Q4_K_M whose numeric cells read "pending hardware". Add a paragraph on the fetch script and the single-file vs split GGUF caveat.
- `docs/operations.md`: new sections "GPU Check" (before Start), "Fetch a Model", and "WebUI Secret" describing the guard. Existing headings and the exact sentence "Public internet exposure is out of scope" stay.
- `README.md`: quickstart becomes: host setup doc, check-context, check-gpu, fetch-model, copy `.env` and set secret, switch-model, start, health, benchmark.
- `CLAUDE.md`: commands block gains `check-gpu.ps1` and `fetch-model.ps1`; conventions note the `WEBUI_SECRET_KEY` guard and that `.env` parsing now spans seven scripts.

### 7. Tests

Extend the existing literal-content scripts, no new framework.

`tests/assert-project-shape.ps1` adds:

- `.env.example` contains `^HOST_JARVIS_DATA_DIR=/srv/llm/jarvis-data$`.
- `.gitignore` contains `^jarvis-data/$`.
- `docs/host-setup.md` exists and contains `nvidia-ctk runtime configure` and `nvidia-container-toolkit`.
- `docs/models.md` contains `Qwen2.5-7B-Instruct` and `Measured`.
- `docs/operations.md` contains `scripts/check-gpu\.ps1` and `scripts/fetch-model\.ps1`.
- `README.md` contains `scripts/fetch-model\.ps1`.

`tests/assert-script-contracts.ps1` adds:

- `scripts/check-gpu.ps1` contains `--gpus all` and `nvidia-smi`.
- `scripts/fetch-model.ps1` contains `HOST_MODEL_DIR`, `huggingface_hub`, `param\(.*\$Repo`, and `switch-model\.ps1`.
- `scripts/benchmark.ps1` contains `predicted_per_second` and `generated_tokens_per_second`.
- `scripts/start.ps1` contains `WEBUI_SECRET_KEY` and `change-me-before-use`.

### 8. Exit criteria

Two layers, because the hardware is not in the machine yet.

Implementation plan is complete when:

- All files above exist and both test scripts pass.
- `check-gpu.ps1` run today fails with the documented "toolkit not installed" message rather than an unhandled Docker error.
- `fetch-model.ps1` is exercised at least once against the real host (the download does not need a GPU) and the file appears under `HOST_MODEL_DIR`.
- `start.ps1` refuses the default secret and accepts a set one.

Phase 0 itself is complete when the operator has:

- Installed the card and toolkit per `docs/host-setup.md` and `check-gpu.ps1` prints the RTX 3060.
- Started the stack and `health.ps1` passes.
- Run `benchmark.ps1` and replaced the "pending hardware" row in `docs/models.md` with measured numbers, committed.

## Decisions this phase records

- Triage latency target: one email classified in under 10 seconds. The benchmark's generated tok/s and prompt tok/s are the inputs; Phase 1's spec picks the context size from them.
- `LLM_CONTEXT_SIZE` stays 4096 until measured; raise to 8192 in `.env` if VRAM allows, and note the choice in `docs/models.md`.

## Out of scope

Anything in Phase 1 or later; Ollama; automated downloads from gated repositories; changes to `compose.yaml`; authentication or TLS.
