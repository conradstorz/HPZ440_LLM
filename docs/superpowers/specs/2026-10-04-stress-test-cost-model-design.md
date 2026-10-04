# Stress Test and Tokens-per-Dollar Cost Model Design

Status: Proposed
Updated: 2026-10-04
Roadmap phase: cross-cutting (capacity and economics). Does not change a permission stage.

## Purpose

Answer two questions with measured numbers instead of guesses:

1. **How much can the HPZ440 actually serve?** Aggregate output throughput, time to first
   token, and latency percentiles under real concurrency, not the single-request figure in
   `docs/models.md`.
2. **At what monthly volume is owning the box cheaper than renting a hosted model of the
   same class?** Expressed as a break-even token volume per month, because "tokens per
   dollar" is unbounded for hardware you already own.

The deliverable is a repeatable script plus a written comparison. No change to Jarvis's
behaviour, permissions, or data.

## Facts carried in

- `compose.yaml` runs `llm-api` with `--host`, `--port`, `--model`, `--ctx-size`,
  `--n-gpu-layers` and **no `--parallel`**. llama.cpp therefore serves one slot. Any
  concurrency measured today is queueing delay, not parallel throughput.
- `--ctx-size` is the **total** KV budget, divided across slots: `--parallel 4
  --ctx-size 8192` gives each slot 2048 tokens.
- `LLM_CONTEXT_SIZE` in `.env` feeds both llama.cpp's `--ctx-size` and the `jarvis`
  service's `JARVIS_CONTEXT_TOKENS` (`compose.yaml`, commented to that effect). Changing it
  changes Jarvis's budget.
- Measured 2026-09-30 at one slot, context 8192: **851 prefill tok/s, 61.9 decode tok/s**
  (`benchmarks/benchmark-20260930-131153.json`). The 13.7x gap between prefill and decode is
  why a single "tokens" unit is meaningless.
- That same run requested `max_tokens: 128` and the model stopped at 23 tokens. The existing
  benchmark measures model verbosity as much as hardware speed.
- The run also reports `cached_tokens: 5` — llama.cpp reuses a prompt prefix across requests.
- Qwen2.5-7B-Instruct is 28 layers with 4 grouped KV heads of 128 dims, so fp16 KV cache
  costs `28 x 2 x 512 x 2 B` = **56 KiB per token**. At 8 slots x 2048 tokens that is
  ~0.9 GB, against ~4.7 GB of weights on a 12 GB RTX 3060. The widest sweep point fits.
- Scripts in `scripts/` target `http://localhost:<port>`, which only resolves through the
  SSH tunnel (`docs/operations.md:39`).
- `tests/assert-project-shape.ps1` and `tests/assert-script-contracts.ps1` regex-match the
  literal content of `scripts/*.ps1`, `docs/*.md`, `compose.yaml`, `.env.example`, and
  `README.md`.
- `.env` parsing is duplicated across eleven scripts in two idioms: a full
  `Get-Content | -match '^[A-Z0-9_]+=.*$'` block (`health.ps1`, `benchmark.ps1`) and
  per-key `Select-String` (the other nine).

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Cost model | **Break-even monthly volume** | Conrad's choice. Tokens per dollar of capex diverges as the box's life grows; break-even volume is finite, decision-relevant, and free of an arbitrary amortization window in the headline. |
| Concurrency | **Sweep `--parallel` 1/2/4/8** | Conrad's choice. Hosted API pricing reflects batched inference; comparing it to single-slot llama.cpp understates the HPZ440 by the batching factor. |
| Comparison set | **Hosted small-open models + other local hardware** | Conrad's choice. Hosted small-open (Llama-3.1-8B, Qwen-class) is the only quality-matched row against Qwen2.5-7B Q4_K_M. Frontier APIs are excluded: their price next to a 7B's throughput is not a like-for-like claim. |
| Load generator | **Python `bench/` package, PowerShell wrapper** | Eight concurrent SSE streams with per-request TTFT needs real async I/O. `uv` is already the project's Python runner. The wrapper keeps the repo's `scripts/*.ps1` entry-point convention and `.env` parsing. |
| Server mutation | **Rewrite `.env`, restart, restore** | A compose override file is cleaner in isolation but adds a second source of truth for ports and model path. The sweep is an operator-run, foreground, minutes-long job; a restore in `finally` is adequate. |
| Fixed output length | **`max_tokens` + `"ignore_eos": true`** | Every request must emit an identical token count or throughput is confounded with verbosity. |
| Prompt uniqueness | **Distinct prompt per client** | Identical prompts share a cached prefix across slots and inflate prefill. |
| Endpoint | **`http://hpz440:8080`** | A tunnel multiplexes 8 streams over one TCP connection and becomes the bottleneck. Port 8080 is the inference service; 8090 is the Jarvis agent and silently drops `tools`. |
| Context-length scaling | **Out of scope** | Prompt length is fixed at one representative value. Sweeping both slots and context doubles the matrix for a question nobody asked. |

## Layout

New:

```
bench/pyproject.toml            uv project, deps: httpx
bench/stress.py                 async load generator, sweep driver, JSON writer
bench/cost.py                   break-even model over a measured run + a prices file
bench/prices.json               hosted and hardware prices, each with source URL and date
bench/tests/test_cost.py        cost arithmetic against hand-computed fixtures
scripts/stress-test.ps1         wrapper: .env parse, restart per sweep point, uv run, restore
docs/cost-model.md              the written comparison and its assumptions
```

Modified: `compose.yaml` (`--parallel ${LLM_PARALLEL:-1}`), `.env.example` (`LLM_PARALLEL=1`
with a comment that raising it divides `LLM_CONTEXT_SIZE` across slots),
`docs/models.md` (throughput rows appended to the Measured table),
`tests/assert-project-shape.ps1` and `tests/assert-script-contracts.ps1` (assertions for the
new script and doc), `.gitignore` (`benchmarks/` already ignored; confirm the new output
names fall under it), `README.md` and `docs/operations.md` (one line each for the new
command).

## How the sweep runs

For each `N` in `1, 2, 4, 8`:

1. Rewrite `.env` so `LLM_PARALLEL = N` and `LLM_CONTEXT_SIZE = N * 2048`, holding
   **2048 tokens per slot** fixed across the sweep so slot count is the only variable.
   `--parallel` is added to `compose.yaml` as `${LLM_PARALLEL:-1}`, defaulting to today's
   behaviour so a normal `start.ps1` is unchanged. Note that the `N = 1` point therefore runs
   at context 2048, not the production 8192 — its decode rate is comparable to the other
   sweep points but not directly to the `docs/models.md` rows.
2. `docker --context hpz440 compose up -d llm-api`, then poll `/v1/models` until it answers.
3. Sample GPU telemetry at 1 Hz in a throwaway container for 20 s with no load — the **idle
   baseline**.
4. Fire `N` concurrent streaming clients. Each client issues **5 sequential requests**, each
   with a distinct ~1000-token prompt and a fixed `max_tokens` of 300 with `ignore_eos`. The
   first request per client is discarded as warm-up, leaving `N x 4` latency samples — enough
   for a p95 even at `N = 1`.
5. Sample GPU telemetry at 1 Hz throughout, in parallel with the load.

Then restore `.env` to its original bytes and bring `llm-api` back up at
`LLM_CONTEXT_SIZE=8192, LLM_PARALLEL=1`. This happens in a `finally` block, including on
Ctrl+C.

GPU telemetry reuses the `check-gpu.ps1` throwaway-container pattern:

```
nvidia-smi --query-gpu=power.draw,utilization.gpu,memory.used --format=csv,noheader,nounits -l 1
```

## Metrics recorded

Per sweep point, written to `benchmarks/stress-<stamp>.json`:

| Field | Meaning |
| --- | --- |
| `slots` | `--parallel` value |
| `ctx_per_slot` | `--ctx-size / slots` |
| `aggregate_output_tps` | total generated tokens across clients / wall time of the round |
| `per_client_output_tps` | aggregate / slots |
| `prefill_tps` | summed `timings.prompt_n` / summed `timings.prompt_ms` |
| `ttft_ms_p50`, `ttft_ms_p95` | first SSE delta per request |
| `latency_ms_p50`, `latency_ms_p95` | request start to final chunk |
| `gpu_watts_idle`, `gpu_watts_mean`, `gpu_watts_max` | from the telemetry sampler |
| `vram_mb_max` | peak `memory.used` |
| `cached_tokens_total` | from `usage.prompt_tokens_details`; above 1% of total prompt tokens the prefill figure is flagged invalid |

`cached_tokens_total` is a self-check, not a result: if distinct prompts still share a
prefix, the run sets `prefill_valid: false` rather than quietly reporting an inflated prefill
rate.

## Cost model

Units are **requests at a fixed mix of 1000 input and 300 output tokens** — Jarvis-
representative, since triage feeds a message body in and gets a short classification out. A
"mixed Mtok" is 1,000,000 tokens at that ratio: 769,231 input and 230,769 output.

```
capex_monthly   = 300 / 36                                   = $8.33
power_monthly   = (W_idle * (720 - h_active) + W_load * h_active) / 1000 * 0.17
cost_monthly    = capex_monthly + power_monthly
hosted_per_Mmix = price_in * 0.769231 + price_out * 0.230769   ($ per Mtok, each side)
break_even_Mmix = cost_monthly / hosted_per_Mmix
```

Inputs: **capex $300** (RTX 3060, Conrad, 2026-09-29), **$0.17/kWh**, 36-month life,
720 h/month powered. `W_idle` and `W_load` come from the sweep. `h_active` is a parameter
reported across a range (30, 100, 300, 720 h/month) rather than a single guess.

Idle watts are charged for all un-active hours because the HPZ440 stays powered. At low
volume that term dominates, so the break-even figure is deliberately not flattering.

Worked example, to show the shape only — real watts come from the sweep. At `W_idle` 12 W,
`W_load` 170 W, `h_active` 60: power is $3.08/month, total $11.41/month. Against a
hypothetical $0.20/Mtok both ways, break-even is **57 mixed Mtok/month**, about 44,000
requests, or 1,460/day. The plausible conclusion is that the box wins on privacy and
latency long before it wins on price; the spec does not assume that, it reports it.

### Honesty constraints

- Every price in `bench/prices.json` carries a `source_url` and a `retrieved` date, fetched
  at write time. No price from memory. Anthropic figures, if ever added, come from the
  `claude-api` skill.
- The hosted row names the specific model (e.g. Llama-3.1-8B-Instruct) and provider, so the
  quality tier is visible. Frontier models are excluded by decision above.
- Local-hardware rows (RTX 4090, Mac mini M4, DGX Spark) are **published benchmark numbers,
  not measured here**, and are labelled as such with their sources.
- `nvidia-smi` reports GPU-only draw. Whole-box draw on an HP Z440 is materially higher and
  unmeasured without a wall meter. `docs/cost-model.md` states this, and gives the
  break-even figure under GPU-only watts as a **lower bound on cost** — so the real
  break-even volume is higher than reported.

## Testing

- `bench/tests/test_cost.py` — the break-even arithmetic against hand-computed fixtures,
  including the worked example above, and the degenerate cases `h_active = 0` and
  `h_active = 720`. Pure functions over a dict; no network, no GPU.
- The load generator is checked against a local stub HTTP server that emits a fixed number
  of SSE chunks on a known delay, asserting TTFT and aggregate-tok/s arithmetic. No real
  model needed.
- `tests/assert-project-shape.ps1` gains assertions that `scripts/stress-test.ps1` and
  `docs/cost-model.md` exist and that `compose.yaml` carries `${LLM_PARALLEL:-1}`.
- `tests/assert-script-contracts.ps1` gains assertions that the wrapper restores `.env` in a
  `finally` block and targets `hpz440`, not `localhost`.

The sweep itself is not tested by CI — it needs the GPU. It is an operator-run command whose
output is a committed artifact.

## Failure handling

| Failure | Behaviour |
| --- | --- |
| `llm-api` does not come healthy after a restart | Abort the sweep, restore `.env`, report which slot count failed. Partial results already collected are still written. |
| Out of VRAM at a high slot count | Caught as a container start failure; the run records that slot count as `oom` and continues to the restore step rather than retrying. |
| A single request errors mid-stream | The round is discarded and retried once; a second failure fails that slot count, not the sweep. |
| Ctrl+C | `finally` restores `.env` and restarts `llm-api` at the production settings. |
| `nvidia-smi` container unavailable | The sweep continues with null watts and `docs/cost-model.md` cannot be generated; throughput results are still valid and written. |

## Out of scope

Context-length scaling, quantization comparison (Q5_K_M vs Q4_K_M), speculative decoding,
alternative servers (vLLM, TGI), frontier-model price rows, whole-box power measurement, and
any change to Jarvis or the permission stage.
