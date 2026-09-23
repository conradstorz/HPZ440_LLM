# Models

Use 7B instruct GGUF models for the default RTX 3060 12GB profile.

Recommended starting quantizations:

- `Q4_K_M`: best first choice for fitting comfortably in 12GB VRAM.
- `Q5_K_M`: higher quality, still plausible for 7B models depending on context size.

Place model files on the HPZ440 host under `/srv/llm/models` unless `.env` sets a different `HOST_MODEL_DIR`.

Inside the container, models are mounted at `/models`, so `LLM_MODEL_PATH` should look like `/models/name.gguf`.

Do not commit model files. The repository ignores `*.gguf`, `*.safetensors`, checkpoints, and generated model artifacts.

## Fetching a model

`pwsh -NoProfile -File scripts/fetch-model.ps1` downloads one GGUF from Hugging Face straight into `HOST_MODEL_DIR` on the host, using a one-shot container. The default is `bartowski/Qwen2.5-7B-Instruct-GGUF` / `Qwen2.5-7B-Instruct-Q4_K_M.gguf`. Override with `-Repo` and `-File`.

Prefer single-file GGUF builds. `fetch-model.ps1` downloads one named file per invocation. llama.cpp itself loads split GGUFs (for example Qwen's official `Qwen/Qwen2.5-7B-Instruct-GGUF`, where `q4_k_m` ships as `-00001-of-00002.gguf` and `-00002-of-00002.gguf`): run `fetch-model.ps1` once per shard with the same `-Repo`, then point `switch-model.ps1` at the first shard; llama.cpp finds the companions in the same directory. Gated repositories (Llama, Gemma) need an authenticated `hf` CLI on the host and a manual copy into `HOST_MODEL_DIR`.

## Measured

Filled in from `scripts/benchmark.ps1` output (`generated_tokens_per_second`) on the real hardware. One row per model and context size tried.

| Model | Quantization | Context | Generated tok/s | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| Qwen2.5-7B-Instruct | Q4_K_M | 4096 | pending hardware | pending hardware | First Phase 0 target. |

Triage target for Phase 1: one email classified in under 10 seconds. If measured throughput allows, raise `LLM_CONTEXT_SIZE` to 8192 in `.env` and add a row here.
