# HPZ440 Local LLM Design

## Purpose

Create an operations project for running and managing local 7B-class LLMs on the HPZ440 LAN server with an RTX 3060 12GB GPU. The project should provide a local OpenAI-compatible API, a browser chat UI, and simple operational tooling for model setup, server lifecycle, health checks, switching, and benchmarking.

## Constraints

- Host: HPZ440 server on the LAN.
- GPU: NVIDIA RTX 3060 with 12GB VRAM.
- Model class: 7B models, preferably quantized GGUF files suitable for `llama.cpp`.
- Container runtime: use the existing remote Docker CLI context `hpz440`; do not rely on local Docker Desktop or local containers.
- Secrets, model files, generated logs, and benchmark artifacts must not be committed.

## Recommended Architecture

Use Docker Compose against the remote `hpz440` Docker context to run two primary services:

1. `llama.cpp` server for inference and OpenAI-compatible API access.
2. Open WebUI for an interactive browser chat interface backed by the API server.

The repository should also include scripts and documentation for common operator workflows:

- Check that the remote Docker context is selected and reachable.
- Start and stop the stack.
- Run a health check against the API endpoint.
- List configured local models.
- Switch the active model by editing a local environment file or compose override.
- Run a small benchmark prompt and record output outside version control.

## Serving Stack

`llama.cpp` is the preferred inference server because it is lightweight, works well with GGUF quantized models, exposes an OpenAI-compatible API, and allows explicit control over GPU offload and context settings. For an RTX 3060 12GB, the default profile should assume a 7B instruct model in a 4-bit or 5-bit quantization.

Open WebUI should connect to the local API endpoint and provide the chat surface. It should persist UI data in a Docker volume or host-mounted data directory excluded from git.

## Repository Shape

The initial project should be infrastructure-first rather than application-heavy:

```text
.
├── .env.example
├── .gitignore
├── README.md
├── compose.yaml
├── docs/
│   ├── models.md
│   ├── operations.md
│   └── superpowers/specs/2026-09-21-hpz440-local-llm-design.md
├── models/
│   └── .gitkeep
└── scripts/
    ├── check-context.ps1
    ├── health.ps1
    ├── list-models.ps1
    ├── start.ps1
    └── stop.ps1
```

PowerShell scripts fit the Windows workstation environment while still driving the remote Linux Docker host through the Docker CLI context.

## Configuration

Use `.env.example` as the committed template and `.env` as the local untracked operator configuration.

Expected configuration values:

- `DOCKER_CONTEXT=hpz440`
- `LLM_MODEL_PATH=/models/<model>.gguf`
- `LLM_CONTEXT_SIZE=4096`
- `LLM_GPU_LAYERS=999`
- `LLM_HOST_PORT=8080`
- `WEBUI_HOST_PORT=3000`
- optional API key values if the selected server image supports them.

The default model path should reference the container path, not a workstation path. Host model placement should be documented separately because it depends on the HPZ440 filesystem layout.

## Model Management

This project should not download large model weights into git. The `models/` directory is only a documented placeholder for local or mounted model files. `.gitignore` must exclude common large model formats and model metadata artifacts, including GGUF, safetensors, PyTorch checkpoints, ONNX files, and tokenizer caches where appropriate.

The docs should recommend starting with a 7B instruct GGUF quantization such as Q4_K_M or Q5_K_M, then adjusting context size and GPU layer settings based on VRAM behavior.

## Operations

The baseline operator workflow should be:

1. Put a GGUF model on the HPZ440 in the configured model directory.
2. Copy `.env.example` to `.env` and set the model filename/path.
3. Run `scripts/check-context.ps1` to verify Docker is pointed at `hpz440`.
4. Run `scripts/start.ps1` to start the API server and WebUI.
5. Run `scripts/health.ps1` to verify the API endpoint responds.
6. Open the WebUI from another LAN machine.

## Alternatives Considered

Ollama plus Open WebUI would be simpler to operate and has a strong model management experience, but it hides more serving configuration and makes the project less explicit about GPU tuning and reproducible server flags.

vLLM would be a better choice for higher-throughput serving, but it is heavier, more memory-hungry, and less natural for GGUF quantized models on a 12GB GPU.

## Success Criteria

- A LAN client can call an OpenAI-compatible endpoint served from the HPZ440.
- A LAN browser can use Open WebUI against the same backend.
- The project documents where to place models and how to choose 7B quantization levels appropriate for 12GB VRAM.
- Scripts make common lifecycle and health-check tasks repeatable.
- Git ignores secrets, model weights, generated data, logs, and benchmark output.

## Initial Non-Goals

- Multi-user authentication hardening beyond Open WebUI's built-in capabilities.
- Automated model downloading from gated providers.
- Kubernetes, GPU scheduling, or multi-node orchestration.
- Training, fine-tuning, or embedding pipelines.
- Public internet exposure.
