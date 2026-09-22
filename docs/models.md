# Models

Use 7B instruct GGUF models for the default RTX 3060 12GB profile.

Recommended starting quantizations:

- `Q4_K_M`: best first choice for fitting comfortably in 12GB VRAM.
- `Q5_K_M`: higher quality, still plausible for 7B models depending on context size.

Place model files on the HPZ440 host under `/srv/llm/models` unless `.env` sets a different `HOST_MODEL_DIR`.

Inside the container, models are mounted at `/models`, so `LLM_MODEL_PATH` should look like `/models/name.gguf`.

Do not commit model files. The repository ignores `*.gguf`, `*.safetensors`, checkpoints, and generated model artifacts.
