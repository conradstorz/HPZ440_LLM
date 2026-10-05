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

Filled in from either `scripts/benchmark.ps1` output (`generated_tokens_per_second`, single request) or `scripts/stress-test.ps1` output (concurrency sweep, aggregate across slots) on the real hardware. The Notes cell says which script produced the row and, for sweep rows, whether the figure is aggregate or per-client. One row per model and context size tried.

| Model | Quantization | Context | Generated tok/s | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| Qwen2.5-7B-Instruct | Q4_K_M | 4096 | 56.4 | 2026-09-29 | `benchmark.ps1`, single request. Prompt 186.9 tok/s, 4.7 GB VRAM used, 128 max tokens. `benchmarks/benchmark-20260929-202137.json`. |
| Qwen2.5-7B-Instruct | Q4_K_M | 8192 | 61.9 | 2026-09-30 | `benchmark.ps1`, single request. Prompt 851 tok/s, 128 max tokens. Jarvis triage: 2.6 s/message median (capture to draft). `benchmarks/benchmark-20260930-131153.json`. |
| Qwen2.5-7B-Instruct | Q4_K_M | 2048 (1x2048) | 58.7 | 2026-10-05 | `stress-test.ps1`, 1 slot — aggregate and per-client are the same at 1 slot. Sweep baseline, 2048 ctx/slot, 1000-token prompts, 300 tokens with ignore_eos. `benchmarks/stress-20261005-091820.json`. |
| Qwen2.5-7B-Instruct | Q4_K_M | 4096 (2x2048) | 99.0 (aggregate) | 2026-10-05 | Aggregate across 2 slots; 49.5 tok/s per client. `stress-test.ps1`, 2 slots, 2048 ctx/slot, 1000-token prompts, 300 tokens with ignore_eos. `benchmarks/stress-20261005-091820.json`. |
| Qwen2.5-7B-Instruct | Q4_K_M | 8192 (4x2048) | 127.3 (aggregate) | 2026-10-05 | Aggregate across 4 slots; 31.8 tok/s per client. `stress-test.ps1`, 4 slots, 2048 ctx/slot, 1000-token prompts, 300 tokens with ignore_eos. `benchmarks/stress-20261005-091820.json`. |
| Qwen2.5-7B-Instruct | Q4_K_M | 16384 (8x2048) | 145.7 (aggregate) | 2026-10-05 | Aggregate across 8 slots; 18.2 tok/s per client. `stress-test.ps1`, 8 slots, 2048 ctx/slot, 1000-token prompts, 300 tokens with ignore_eos. `benchmarks/stress-20261005-091820.json`. |

Triage target for Phase 1: one email classified in under 10 seconds. Met on 2026-09-30 (2.6 s median). `LLM_CONTEXT_SIZE=8192` is the working value for Jarvis, and `.env.example` now ships 8192; the `compose.yaml` fallback stays 4096 for stacks brought up without a `.env`.

Concurrency: `scripts/stress-test.ps1` measured aggregate throughput at 1, 2, 4, and 8 slots
with 2048 tokens of context each. See `docs/cost-model.md` for the full table and what it
means for the economics. The single-slot rows above at context 4096 and 8192 are not directly
comparable to the sweep rows, which all run at 2048 per slot.
