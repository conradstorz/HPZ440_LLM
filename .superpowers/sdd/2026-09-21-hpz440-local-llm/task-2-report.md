# Task 2 Report

Status: DONE

Files changed:

- `compose.yaml`
- `tests/assert-project-shape.ps1`

Validation:

```text
pwsh -NoProfile -File tests/assert-project-shape.ps1
Project guardrail checks passed.

docker --context hpz440 compose --env-file .env.example config
Rendered hpz440-llm services successfully.

git status --short
Untracked project files listed; no tracked modifications shown.
```

Concerns: none.

Self-review:

- `llm-api` uses the CUDA llama.cpp server image and exposes `${LLM_HOST_PORT:-8080}`.
- `open-webui` points at `http://llm-api:8080/v1` and exposes `${WEBUI_HOST_PORT:-3000}`.
- The model mount and GPU reservation are present.
