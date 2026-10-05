# Stress Test and Tokens-per-Dollar Cost Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the HPZ440's real concurrent throughput and power draw, then report the monthly token volume at which owning the RTX 3060 beats renting a hosted model of the same class.

**Architecture:** A new `bench/` Python package (uv, httpx) holds two pure-function modules — `metrics.py` (percentiles and throughput arithmetic) and `cost.py` (break-even model) — plus `load.py`, an async client that drives N concurrent streaming completions against `http://hpz440:8080` and prints one JSON object per slot count. `scripts/stress-test.ps1` owns the sweep loop and server lifecycle: it rewrites `.env`, restarts `llm-api`, samples `nvidia-smi` in a throwaway container, invokes the Python load for that slot count, and restores `.env` in a `finally` block. Results land in `benchmarks/stress-<stamp>.json`; the written comparison goes in `docs/cost-model.md`.

**Tech Stack:** Python 3.12 + httpx + pytest under `uv`; PowerShell 7 for orchestration; Docker CLI context `hpz440`; llama.cpp `server-cuda`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-04-stress-test-cost-model-design.md`. Read it before Task 1.
- **Never chain shell commands with `&&`.** The permission system blocks chained commands. Use separate tool calls. (User's global CLAUDE.md.)
- Python runs only through `uv`: `uv sync`, `uv run python`, `uv run pytest`. Never `pip install`, never `python -m venv`, never `activate`.
- Load generator targets **`http://hpz440:8080`** (the llama.cpp inference service), never `localhost` and never port 8090 (the Jarvis agent, which silently drops `tools` and is not the model).
- Docker always via `docker --context hpz440`. Never start local containers, never switch to `default` or `desktop-linux`.
- Capex is **$300** (RTX 3060, purchased 2026-09-29). Electricity is **$0.17/kWh**. Amortization is **36 months**. Powered hours per month is **720**.
- Token mix is **1000 input / 300 output** per request. A "mixed Mtok" is 1,000,000 tokens at that ratio.
- Every price written into `bench/prices.json` carries a literal `source_url` and a `retrieved` ISO date obtained by fetching at write time. **No price from memory.**
- Local-hardware comparison rows are published third-party benchmarks, labelled as such with sources. They are not measured here.
- `tests/assert-project-shape.ps1` and `tests/assert-script-contracts.ps1` regex-match literal file content. Any new script, new `.env.example` key, new `compose.yaml` line, or new doc heading needs its assertion added **in the same task**.
- `benchmarks/` is already in `.gitignore`. Raw sweep JSON is never committed; only the derived tables in `docs/models.md` and `docs/cost-model.md` are.
- Commit after every task. Branch is `bench/stress-test-cost-model`, already created.

## File Structure

| File | Responsibility |
| --- | --- |
| `compose.yaml` | Add `--parallel ${LLM_PARALLEL:-1}` to `llm-api`. Nothing else changes. |
| `.env.example` | Add `LLM_PARALLEL=1` with the context-division warning. |
| `bench/pyproject.toml` | uv project root. Deps `httpx`, dev `pytest`. Separate from `jarvis/` — it is a tool, not part of the app. |
| `bench/bench/metrics.py` | Pure arithmetic over a list of request samples → one summary dict. No I/O. |
| `bench/bench/cost.py` | Pure arithmetic: monthly cost of ownership, hosted cost per mixed Mtok, break-even volume. No I/O. |
| `bench/bench/prices.py` | Load and validate `prices.json`. Rejects any entry missing `source_url` or `retrieved`. |
| `bench/bench/prices.json` | The fetched price data. |
| `bench/bench/load.py` | Async httpx client: N concurrent streaming clients, 5 sequential requests each, emits summary JSON on stdout. |
| `bench/bench/report.py` | Reads a sweep JSON + prices, prints the Markdown tables for the two docs. |
| `bench/tests/` | pytest for `metrics`, `cost`, `prices`, and `load` against a stub SSE server. |

**Layout rule, and it is the one thing most likely to go wrong:** the uv project root is
`bench/` and the importable package is `bench/bench/`, exactly mirroring `jarvis/jarvis/`.
Every pytest command runs with `bench/` as the working directory, and the sweep script invokes
`uv --directory bench run python -m bench.load`. Do not put modules directly in `bench/` —
`from bench import cost` and `python -m bench.load` both need `bench/` on `sys.path` with the
package one level below it.
| `scripts/stress-test.ps1` | Sweep loop, `.env` rewrite and restore, container restart, GPU telemetry, result merge. |
| `docs/cost-model.md` | The written comparison, its assumptions, and its honesty caveats. |
| `docs/models.md` | Measured table gains the sweep rows. |

Task order is dependency order: Task 1 unblocks the server, Tasks 2–4 are pure Python with no hardware, Task 5 is the orchestration, Task 6 is the real run and the writeup.

---

### Task 1: `--parallel` plumbing

Without this the server has one slot and the whole sweep is meaningless. Default stays `1`, so an ordinary `start.ps1` behaves exactly as today.

**Files:**
- Modify: `compose.yaml` (the `llm-api` `command:` list)
- Modify: `.env.example`
- Modify: `tests/assert-project-shape.ps1`

- [ ] **Step 1: Add the failing assertions first**

Append to `tests/assert-project-shape.ps1`, immediately **before** the `$Gitkeep` block near the end of the file:

```powershell
Assert-FileContains 'compose.yaml' '\$\{LLM_PARALLEL:-1\}'
Assert-FileContains '.env.example' '^LLM_PARALLEL=1$'
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`

Expected: FAIL with `Expected compose.yaml to contain pattern: \$\{LLM_PARALLEL:-1\}`

- [ ] **Step 3: Add the flag to compose.yaml**

In `compose.yaml`, inside `services.llm-api.command`, after the `--ctx-size` pair and before `--n-gpu-layers`, insert:

```yaml
      - --parallel
      - "${LLM_PARALLEL:-1}"
```

The resulting `command` block reads:

```yaml
    command:
      - --host
      - 0.0.0.0
      - --port
      - "8080"
      - --model
      - "${LLM_MODEL_PATH:-/models/model.gguf}"
      - --ctx-size
      - "${LLM_CONTEXT_SIZE:-4096}"
      - --parallel
      - "${LLM_PARALLEL:-1}"
      - --n-gpu-layers
      - "${LLM_GPU_LAYERS:-999}"
```

- [ ] **Step 4: Add the key to .env.example**

In `.env.example`, replace the line `LLM_GPU_LAYERS=999` with:

```
LLM_GPU_LAYERS=999
# Concurrent llama.cpp slots. LLM_CONTEXT_SIZE is the TOTAL KV budget and is divided
# across slots: LLM_PARALLEL=4 with LLM_CONTEXT_SIZE=8192 gives each slot 2048 tokens.
# Raise only for a benchmark sweep; scripts/stress-test.ps1 sets and restores it.
LLM_PARALLEL=1
```

- [ ] **Step 5: Run both test scripts to verify they pass**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: PASS, ending `Project guardrail checks passed.`

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: PASS (unchanged by this task, run to confirm no regression).

- [ ] **Step 6: Add the key to the operator's own .env**

`.env` is untracked, so it does not get the new key automatically. Run:

```bash
grep -c '^LLM_PARALLEL=' .env
```

If the count is `0`, append it:

```bash
printf 'LLM_PARALLEL=1\n' >> .env
```

Expected: `grep '^LLM_PARALLEL=' .env` now prints `LLM_PARALLEL=1`.

- [ ] **Step 7: Verify the stack still comes up unchanged**

Run: `pwsh -NoProfile -File scripts/start.ps1`
Then: `pwsh -NoProfile -File scripts/health.ps1`
Expected: `/v1/models` answers, WebUI root answers, jarvis `/health` answers. A `--parallel 1` server is behaviourally identical to no flag.

- [ ] **Step 8: Commit**

```bash
git add compose.yaml .env.example tests/assert-project-shape.ps1
git commit -m "feat: make llama.cpp slot count configurable via LLM_PARALLEL"
```

---

### Task 2: Cost model arithmetic

Pure functions, hand-checked fixtures, no network and no GPU. This is the part that has to be right — the break-even number is the deliverable.

**Files:**
- Create: `bench/pyproject.toml`
- Create: `bench/bench/__init__.py`
- Create: `bench/bench/cost.py`
- Create: `bench/tests/test_cost.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces, all in `bench/bench/cost.py`:
  - `MIX_INPUT_TOKENS: int = 1000`, `MIX_OUTPUT_TOKENS: int = 300`
  - `HOURS_PER_MONTH: int = 720`, `AMORTIZATION_MONTHS: int = 36`
  - `CAPEX_USD: float = 300.0`, `PRICE_PER_KWH: float = 0.17`
  - `mix_fractions(input_tokens: int = MIX_INPUT_TOKENS, output_tokens: int = MIX_OUTPUT_TOKENS) -> tuple[float, float]`
  - `requests_per_mixed_mtok(input_tokens: int = ..., output_tokens: int = ...) -> float`
  - `monthly_power_cost(watts_idle: float, watts_load: float, hours_active: float, price_per_kwh: float = PRICE_PER_KWH, hours_per_month: int = HOURS_PER_MONTH) -> float`
  - `monthly_cost_of_ownership(capex_usd: float = CAPEX_USD, *, watts_idle: float, watts_load: float, hours_active: float, price_per_kwh: float = PRICE_PER_KWH, amortization_months: int = AMORTIZATION_MONTHS) -> float`
  - `hosted_cost_per_mixed_mtok(price_in_per_mtok: float, price_out_per_mtok: float, input_tokens: int = ..., output_tokens: int = ...) -> float`
  - `break_even_mixed_mtok(monthly_cost_usd: float, hosted_per_mixed_mtok: float) -> float`

- [ ] **Step 1: Create the uv project**

Create `bench/pyproject.toml`:

```toml
[project]
name = "bench"
version = "0.1.0"
description = "Throughput sweep and cost model for the HPZ440 LLM stack"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
]

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["bench"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
filterwarnings = ["error"]
```

Then run, as separate calls:

```bash
cd bench
```

```bash
uv sync
```

Expected: a `bench/.venv` is created and `httpx` plus `pytest` resolve. `.venv/` is already gitignored.

- [ ] **Step 2: Write the failing test**

Create `bench/tests/test_cost.py`:

```python
import pytest

from bench import cost


def test_mix_fractions_sum_to_one():
    frac_in, frac_out = cost.mix_fractions()
    assert frac_in == pytest.approx(1000 / 1300)
    assert frac_out == pytest.approx(300 / 1300)
    assert frac_in + frac_out == pytest.approx(1.0)


def test_requests_per_mixed_mtok():
    # 1,000,000 tokens at 1300 tokens per request.
    assert cost.requests_per_mixed_mtok() == pytest.approx(769.2307, abs=1e-4)


def test_monthly_power_cost_worked_example():
    # 12 W idle for 660 h = 7.920 kWh; 170 W under load for 60 h = 10.200 kWh.
    # 18.120 kWh at $0.17 = $3.0804.
    assert cost.monthly_power_cost(12.0, 170.0, 60.0) == pytest.approx(3.0804, abs=1e-4)


def test_monthly_power_cost_idle_only():
    # hours_active = 0: 12 W for the full 720 h = 8.64 kWh at $0.17 = $1.4688.
    assert cost.monthly_power_cost(12.0, 170.0, 0.0) == pytest.approx(1.4688, abs=1e-4)


def test_monthly_power_cost_fully_loaded():
    # hours_active = 720: no idle hours remain. 170 W x 720 h = 122.4 kWh = $20.808.
    assert cost.monthly_power_cost(12.0, 170.0, 720.0) == pytest.approx(20.808, abs=1e-3)


def test_monthly_power_cost_rejects_impossible_hours():
    with pytest.raises(ValueError):
        cost.monthly_power_cost(12.0, 170.0, 721.0)
    with pytest.raises(ValueError):
        cost.monthly_power_cost(12.0, 170.0, -1.0)


def test_monthly_cost_of_ownership_worked_example():
    # $300 / 36 months = $8.3333 capex, plus $3.0804 power.
    result = cost.monthly_cost_of_ownership(
        watts_idle=12.0, watts_load=170.0, hours_active=60.0
    )
    assert result == pytest.approx(11.4137, abs=1e-4)


def test_hosted_cost_symmetric_prices():
    # Equal input and output prices: the mix cannot change the per-Mtok figure.
    assert cost.hosted_cost_per_mixed_mtok(0.20, 0.20) == pytest.approx(0.20)


def test_hosted_cost_asymmetric_prices():
    # 0.10 * (1000/1300) + 0.40 * (300/1300)
    assert cost.hosted_cost_per_mixed_mtok(0.10, 0.40) == pytest.approx(0.1692307, abs=1e-6)


def test_break_even_worked_example():
    assert cost.break_even_mixed_mtok(11.4137, 0.20) == pytest.approx(57.0685, abs=1e-3)


def test_break_even_rejects_free_hosting():
    with pytest.raises(ValueError):
        cost.break_even_mixed_mtok(11.41, 0.0)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_cost.py -v` from `bench/`
Expected: collection error — `ModuleNotFoundError: No module named 'bench.cost'`

- [ ] **Step 4: Write the implementation**

Create `bench/bench/cost.py`:

```python
"""Cost of ownership and break-even arithmetic for the HPZ440 LLM stack.

Pure functions over numbers. No I/O, no network, no hardware.

"Tokens per dollar" is unbounded for hardware you already own, so the headline
figure here is a break-even monthly token volume: the volume at which paying a
hosted provider costs the same as amortized capex plus electricity.
"""

MIX_INPUT_TOKENS = 1000
MIX_OUTPUT_TOKENS = 300

HOURS_PER_MONTH = 720
AMORTIZATION_MONTHS = 36

CAPEX_USD = 300.0  # RTX 3060 12GB, purchased 2026-09-29.
PRICE_PER_KWH = 0.17  # Conrad's rate, 2026-10.


def mix_fractions(
    input_tokens: int = MIX_INPUT_TOKENS,
    output_tokens: int = MIX_OUTPUT_TOKENS,
) -> tuple[float, float]:
    """Fraction of a mixed-token unit that is input, and that is output."""
    total = input_tokens + output_tokens
    if total <= 0:
        raise ValueError("token mix must be positive")
    return input_tokens / total, output_tokens / total


def requests_per_mixed_mtok(
    input_tokens: int = MIX_INPUT_TOKENS,
    output_tokens: int = MIX_OUTPUT_TOKENS,
) -> float:
    """How many requests one million mixed tokens buys."""
    total = input_tokens + output_tokens
    if total <= 0:
        raise ValueError("token mix must be positive")
    return 1_000_000 / total


def monthly_power_cost(
    watts_idle: float,
    watts_load: float,
    hours_active: float,
    price_per_kwh: float = PRICE_PER_KWH,
    hours_per_month: int = HOURS_PER_MONTH,
) -> float:
    """Electricity for one month.

    Idle watts are charged for every powered hour that is not active, because
    the HPZ440 stays on. At low volume this term dominates.
    """
    if not 0.0 <= hours_active <= hours_per_month:
        raise ValueError(
            f"hours_active must be between 0 and {hours_per_month}, got {hours_active}"
        )
    idle_hours = hours_per_month - hours_active
    kwh = (watts_idle * idle_hours + watts_load * hours_active) / 1000.0
    return kwh * price_per_kwh


def monthly_cost_of_ownership(
    capex_usd: float = CAPEX_USD,
    *,
    watts_idle: float,
    watts_load: float,
    hours_active: float,
    price_per_kwh: float = PRICE_PER_KWH,
    amortization_months: int = AMORTIZATION_MONTHS,
) -> float:
    """Amortized hardware plus electricity, per month."""
    if amortization_months <= 0:
        raise ValueError("amortization_months must be positive")
    capex_monthly = capex_usd / amortization_months
    power = monthly_power_cost(watts_idle, watts_load, hours_active, price_per_kwh)
    return capex_monthly + power


def hosted_cost_per_mixed_mtok(
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    input_tokens: int = MIX_INPUT_TOKENS,
    output_tokens: int = MIX_OUTPUT_TOKENS,
) -> float:
    """Dollars a hosted provider charges for one million mixed tokens.

    Providers price input and output separately, and on this hardware prefill is
    an order of magnitude faster than decode, so a single "tokens" unit is
    meaningless without a fixed mix.
    """
    frac_in, frac_out = mix_fractions(input_tokens, output_tokens)
    return price_in_per_mtok * frac_in + price_out_per_mtok * frac_out


def break_even_mixed_mtok(
    monthly_cost_usd: float,
    hosted_per_mixed_mtok: float,
) -> float:
    """Mixed Mtok per month at which owning costs the same as renting."""
    if hosted_per_mixed_mtok <= 0:
        raise ValueError("hosted price must be positive")
    return monthly_cost_usd / hosted_per_mixed_mtok
```

Create an empty `bench/bench/__init__.py` so `from bench import cost` resolves with
`pythonpath = ["."]` and `python -m bench.load` resolves from `bench/`:

```bash
printf '' > bench/bench/__init__.py
```

There is deliberately no `bench/tests/__init__.py` — pytest's `pythonpath = ["."]` puts
`bench/` on `sys.path`, which is what makes `bench` importable. This mirrors `jarvis/`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_cost.py -v` from `bench/`
Expected: PASS, 11 passed.

- [ ] **Step 6: Confirm the venv is ignored and lockfile is tracked**

Run: `git status --short bench/`
Expected: `bench/pyproject.toml`, `bench/uv.lock`, `bench/bench/__init__.py`, `bench/bench/cost.py`, `bench/tests/` listed as untracked. **`bench/.venv/` must NOT appear** — `.gitignore` already has `.venv/`. If it does appear, add `bench/.venv/` to `.gitignore` in this task.

- [ ] **Step 7: Commit**

```bash
git add bench/pyproject.toml bench/uv.lock bench/bench/__init__.py bench/bench/cost.py bench/tests/
git commit -m "feat(bench): break-even cost model with hand-checked fixtures"
```

---

### Task 3: Price data with mandatory provenance

The loader refuses prices that lack a source and a date. That is the mechanism that keeps recalled numbers out of the comparison.

**Files:**
- Create: `bench/bench/prices.py`
- Create: `bench/bench/prices.json`
- Create: `bench/tests/test_prices.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, in `bench/bench/prices.py`:
  - `@dataclass(frozen=True) HostedPrice` with fields `provider: str`, `model: str`, `usd_per_mtok_in: float`, `usd_per_mtok_out: float`, `source_url: str`, `retrieved: str`
  - `@dataclass(frozen=True) HardwarePrice` with fields `name: str`, `usd: float`, `decode_tps_7b_q4: float | None`, `price_source: str`, `price_note: str`, `benchmark_source: str`, `retrieved: str`, `measured_here: bool`
  - `load_prices(path: Path | str) -> tuple[list[HostedPrice], list[HardwarePrice]]` — raises `ValueError` naming the offending entry if provenance is missing or `retrieved` is not a real `YYYY-MM-DD` calendar date.

**Why a hardware row needs two provenance fields.** A hosted row's input and output price both
appear on one pricing page, so one `source_url` cites both honestly. A hardware row carries two
independently sourced facts — a retail price and a decode tok/s figure — which never come from
the same page. One field cannot cite both: the first implementation attempt cited a 4090's
price to a benchmark blog that contained no price at all. So `price_source` cites the `usd`
figure, `benchmark_source` cites `decode_tps_7b_q4`, and `price_note` says how to read the
price, because "the" price of a GPU is not a single number. Conrad's decision, 2026-10-05.

- [ ] **Step 1: Write the failing test**

Create `bench/tests/test_prices.py`:

```python
import json
from pathlib import Path

import pytest

from bench import prices


GOOD = {
    "hosted": [
        {
            "provider": "ExampleHost",
            "model": "Llama-3.1-8B-Instruct",
            "usd_per_mtok_in": 0.18,
            "usd_per_mtok_out": 0.18,
            "source_url": "https://example.invalid/pricing",
            "retrieved": "2026-10-04",
        }
    ],
    "hardware": [
        {
            "name": "RTX 3060 12GB",
            "usd": 300.0,
            "decode_tps_7b_q4": 61.9,
            "price_source": "Conrad's purchase, 2026-09-29",
            "price_note": "purchase price paid",
            "benchmark_source": "https://example.invalid/bench",
            "retrieved": "2026-10-04",
            "measured_here": True,
        }
    ],
}


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_well_formed_file(tmp_path):
    hosted, hardware = prices.load_prices(_write(tmp_path, GOOD))
    assert len(hosted) == 1
    assert hosted[0].model == "Llama-3.1-8B-Instruct"
    assert hosted[0].usd_per_mtok_out == 0.18
    assert hardware[0].measured_here is True
    assert hardware[0].price_source == "Conrad's purchase, 2026-09-29"
    assert hardware[0].benchmark_source == "https://example.invalid/bench"


def test_rejects_hosted_entry_without_source(tmp_path):
    payload = json.loads(json.dumps(GOOD))
    del payload["hosted"][0]["source_url"]
    with pytest.raises(ValueError, match="Llama-3.1-8B-Instruct"):
        prices.load_prices(_write(tmp_path, payload))


def test_rejects_hardware_entry_without_price_source(tmp_path):
    payload = json.loads(json.dumps(GOOD))
    payload["hardware"][0]["price_source"] = ""
    with pytest.raises(ValueError, match="price_source"):
        prices.load_prices(_write(tmp_path, payload))


def test_rejects_throughput_figure_without_its_own_source(tmp_path):
    """A tok/s number must cite the page that states it, not the price's page."""
    payload = json.loads(json.dumps(GOOD))
    del payload["hardware"][0]["benchmark_source"]
    with pytest.raises(ValueError, match="benchmark_source"):
        prices.load_prices(_write(tmp_path, payload))


def test_allows_missing_benchmark_source_when_there_is_no_figure(tmp_path):
    """decode_tps_7b_q4 null means the figure could not be sourced; that is allowed."""
    payload = json.loads(json.dumps(GOOD))
    payload["hardware"][0]["decode_tps_7b_q4"] = None
    del payload["hardware"][0]["benchmark_source"]
    _hosted, hardware = prices.load_prices(_write(tmp_path, payload))
    assert hardware[0].decode_tps_7b_q4 is None
    assert hardware[0].benchmark_source == ""


def test_rejects_whitespace_only_source(tmp_path):
    payload = json.loads(json.dumps(GOOD))
    payload["hosted"][0]["source_url"] = "   "
    with pytest.raises(ValueError, match="source_url"):
        prices.load_prices(_write(tmp_path, payload))


def test_rejects_malformed_retrieved_date(tmp_path):
    payload = json.loads(json.dumps(GOOD))
    payload["hosted"][0]["retrieved"] = "Oct 2026"
    with pytest.raises(ValueError, match="retrieved"):
        prices.load_prices(_write(tmp_path, payload))


def test_rejects_impossible_retrieved_date(tmp_path):
    """Right shape, no such day. A regex alone would let this through."""
    payload = json.loads(json.dumps(GOOD))
    payload["hosted"][0]["retrieved"] = "2026-02-30"
    with pytest.raises(ValueError, match="retrieved"):
        prices.load_prices(_write(tmp_path, payload))


def test_rejects_undashed_retrieved_date(tmp_path):
    """A real date in the wrong shape. date.fromisoformat alone accepts this."""
    payload = json.loads(json.dumps(GOOD))
    payload["hosted"][0]["retrieved"] = "20261004"
    with pytest.raises(ValueError, match="retrieved"):
        prices.load_prices(_write(tmp_path, payload))


def test_shipped_prices_file_is_valid():
    """The committed prices.json must itself satisfy the provenance rule."""
    path = Path(prices.__file__).resolve().parent / "prices.json"
    hosted, hardware = prices.load_prices(path)
    assert hosted, "no hosted prices recorded"
    assert hardware, "no hardware prices recorded"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_prices.py -v` from `bench/`
Expected: collection error — `ModuleNotFoundError: No module named 'bench.prices'`

- [ ] **Step 3: Write the loader**

Create `bench/bench/prices.py`:

```python
"""Price data with mandatory provenance.

Every number in the comparison must be traceable to a URL and a date it was
fetched. This loader rejects a record that is missing either, so a price
recalled from memory cannot reach the writeup.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class HostedPrice:
    provider: str
    model: str
    usd_per_mtok_in: float
    usd_per_mtok_out: float
    source_url: str
    retrieved: str


@dataclass(frozen=True)
class HardwarePrice:
    name: str
    usd: float
    decode_tps_7b_q4: float | None
    price_source: str
    price_note: str
    benchmark_source: str
    retrieved: str
    measured_here: bool


def _require(record: dict, field: str, label: str) -> str:
    """A provenance field that must be present and not blank."""
    value = str(record.get(field, "") or "").strip()
    if not value:
        raise ValueError(f"{label}: missing {field}. Cite where the number came from; do not recall it.")
    return value


def _check_retrieved(record: dict, label: str) -> str:
    retrieved = str(record.get("retrieved", "") or "").strip()
    # Two checks, because neither alone is enough: fromisoformat accepts "20261004",
    # and the regex alone accepts a well-shaped impossible day like 2026-02-30.
    if not _DATE.match(retrieved):
        raise ValueError(f"{label}: retrieved must be YYYY-MM-DD, got {retrieved!r}")
    try:
        date.fromisoformat(retrieved)
    except ValueError:
        raise ValueError(
            f"{label}: retrieved must be a real calendar date, got {retrieved!r}"
        ) from None
    return retrieved


def load_prices(path: Path | str) -> tuple[list[HostedPrice], list[HardwarePrice]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    hosted: list[HostedPrice] = []
    for record in payload.get("hosted", []):
        label = f"{record.get('provider', '?')}/{record.get('model', '?')}"
        hosted.append(
            HostedPrice(
                provider=record["provider"],
                model=record["model"],
                usd_per_mtok_in=float(record["usd_per_mtok_in"]),
                usd_per_mtok_out=float(record["usd_per_mtok_out"]),
                source_url=_require(record, "source_url", label),
                retrieved=_check_retrieved(record, label),
            )
        )

    hardware: list[HardwarePrice] = []
    for record in payload.get("hardware", []):
        label = record.get("name", "?")
        decode = record.get("decode_tps_7b_q4")
        # A throughput figure must name the page it came from; the price's own source is
        # a separate field because the two never appear on the same page.
        benchmark_source = (
            "" if decode is None else _require(record, "benchmark_source", label)
        )
        hardware.append(
            HardwarePrice(
                name=record["name"],
                usd=float(record["usd"]),
                decode_tps_7b_q4=None if decode is None else float(decode),
                price_source=_require(record, "price_source", label),
                price_note=_require(record, "price_note", label),
                benchmark_source=benchmark_source,
                retrieved=_check_retrieved(record, label),
                measured_here=bool(record.get("measured_here", False)),
            )
        )

    return hosted, hardware
```

- [ ] **Step 4: Fetch the real prices**

Use WebSearch and WebFetch to obtain, **for each** of the following, the current published per-million-token input and output price for a Llama-3.1-8B-Instruct or Qwen-2.5-7B-class instruct model:

- Groq
- Together AI
- DeepInfra

And for each of these, the current retail price plus a published Qwen2.5-7B (or Llama-3-8B) Q4 decode tok/s figure — **each from its own page, recorded in its own field**:

- NVIDIA RTX 4090 (24GB)
- Apple Mac mini M4 (16GB base)
- NVIDIA DGX Spark

For a card sold above its launch MSRP on the secondary market, record the **median of the
listings you actually see**, cite the retailer page in `price_source`, and say so in
`price_note` (for example `secondary-market median of 4 Newegg listings, $3,999-$5,199`).
A single lowest-outlier listing presented as "the" price is a defect. Conrad's decision,
2026-10-05.

Rules:
- Record the exact URL you read the number from, not a search-results page.
- Set `retrieved` to today's date in `YYYY-MM-DD`.
- If a provider does not publish a price for a model in this class, omit that provider and note the omission in `docs/cost-model.md` in Task 6. Do not substitute a guess.
- If a hardware decode figure cannot be sourced, set `decode_tps_7b_q4` to `null` rather than estimating.
- Frontier APIs (Claude, GPT, Gemini) are **excluded by design decision**. Do not add them.

Then create `bench/bench/prices.json` with this exact shape, substituting the fetched values:

```json
{
  "hosted": [
    {
      "provider": "<provider>",
      "model": "<exact model id as the provider names it>",
      "usd_per_mtok_in": 0.0,
      "usd_per_mtok_out": 0.0,
      "source_url": "<exact page you read>",
      "retrieved": "<YYYY-MM-DD>"
    }
  ],
  "hardware": [
    {
      "name": "RTX 3060 12GB (this box)",
      "usd": 300.0,
      "decode_tps_7b_q4": 61.9,
      "price_source": "Conrad's purchase, 2026-09-29",
      "price_note": "purchase price paid",
      "benchmark_source": "benchmarks/benchmark-20260930-131153.json",
      "retrieved": "2026-09-30",
      "measured_here": true
    },
    {
      "name": "<other hardware>",
      "usd": 0.0,
      "decode_tps_7b_q4": null,
      "price_source": "<exact page stating the price>",
      "price_note": "<MSRP | secondary-market median of N listings, $X-$Y | retail>",
      "benchmark_source": "",
      "retrieved": "<YYYY-MM-DD>",
      "measured_here": false
    }
  ]
}
```

The RTX 3060 row is the only entry whose provenance is a purchase and a repo path rather than
URLs — it is the one row measured on this hardware, and `measured_here` is `true` to mark that.
`benchmark_source` is `""` exactly when `decode_tps_7b_q4` is `null`; whenever a figure is
present its own page must be named.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_prices.py -v` from `bench/`
Expected: PASS, 10 passed. `test_shipped_prices_file_is_valid` passing proves every committed price has a source and a date.

- [ ] **Step 6: Commit**

```bash
git add bench/bench/prices.py bench/bench/prices.json bench/tests/test_prices.py
git commit -m "feat(bench): price data with enforced source URL and retrieval date"
```

---

### Task 4: Load generator and metrics

Two separable pieces: `metrics.py` is pure arithmetic tested in isolation, `load.py` is the async client tested against a local stub SSE server. Neither needs the GPU.

**Files:**
- Create: `bench/bench/metrics.py`
- Create: `bench/bench/load.py`
- Create: `bench/tests/test_metrics.py`
- Create: `bench/tests/test_load.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, in `bench/bench/metrics.py`:
  - `@dataclass(frozen=True) RequestSample` with fields `ttft_ms: float`, `latency_ms: float`, `output_tokens: int`, `prompt_tokens: int`, `prompt_ms: float`, `cached_tokens: int`
  - `percentile(values: list[float], p: float) -> float` — linear interpolation, raises `ValueError` on an empty list
  - `summarize(samples: list[RequestSample], wall_seconds: float, slots: int, ctx_per_slot: int) -> dict`
- Produces, in `bench/bench/load.py`:
  - `async def one_request(client: httpx.AsyncClient, base_url: str, model: str, prompt: str, max_tokens: int) -> RequestSample`
  - `async def run_slot_point(base_url: str, model: str, slots: int, ctx_per_slot: int, requests_per_client: int, prompt_tokens: int, max_tokens: int) -> dict`
  - `def main(argv: list[str] | None = None) -> int` — CLI that prints the `summarize` dict as JSON on stdout
  - `def build_prompt(seed: int, approx_tokens: int) -> str` — distinct per seed, so no two clients share a cache prefix

- [ ] **Step 1: Write the failing metrics test**

Create `bench/tests/test_metrics.py`:

```python
import pytest

from bench.metrics import RequestSample, percentile, summarize


def test_percentile_interpolates():
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert percentile([1.0, 2.0, 3.0, 4.0], 0) == pytest.approx(1.0)
    assert percentile([1.0, 2.0, 3.0, 4.0], 100) == pytest.approx(4.0)


def test_percentile_single_value():
    assert percentile([42.0], 95) == pytest.approx(42.0)


def test_percentile_rejects_empty():
    with pytest.raises(ValueError):
        percentile([], 50)


def _sample(**kw) -> RequestSample:
    base = dict(
        ttft_ms=100.0,
        latency_ms=5000.0,
        output_tokens=300,
        prompt_tokens=1000,
        prompt_ms=1000.0,
        cached_tokens=0,
    )
    base.update(kw)
    return RequestSample(**base)


def test_summarize_aggregate_throughput():
    # 4 requests x 300 tokens = 1200 tokens in 10 s wall time.
    samples = [_sample() for _ in range(4)]
    out = summarize(samples, wall_seconds=10.0, slots=2, ctx_per_slot=2048)
    assert out["aggregate_output_tps"] == pytest.approx(120.0)
    assert out["per_client_output_tps"] == pytest.approx(60.0)
    assert out["prompt_tokens_mean"] == pytest.approx(1000.0)
    assert out["requests"] == 4
    assert out["slots"] == 2
    assert out["ctx_per_slot"] == 2048


def test_summarize_prefill_rate():
    # Nothing cached: 1000 prompt tokens computed in 1000 ms = 1000 tok/s per
    # request, and 4 requests at that rate is still 1000 tok/s.
    samples = [_sample() for _ in range(4)]
    out = summarize(samples, wall_seconds=10.0, slots=2, ctx_per_slot=2048)
    assert out["prefill_tps"] == pytest.approx(1000.0)
    assert out["prefill_tokens_computed"] == 4000


def test_summarize_flags_cache_contamination():
    clean = [_sample(cached_tokens=5) for _ in range(4)]  # 20 of 4000 = 0.5%
    assert summarize(clean, wall_seconds=10.0, slots=2, ctx_per_slot=2048)["prefill_valid"] is True

    dirty = [_sample(cached_tokens=500) for _ in range(4)]  # 2000 of 4000 = 50%
    out = summarize(dirty, wall_seconds=10.0, slots=2, ctx_per_slot=2048)
    assert out["prefill_valid"] is False
    assert out["cached_tokens_total"] == 2000


def test_summarize_prefill_rate_counts_only_computed_tokens():
    """Cached tokens were not computed, so they must not inflate the rate.

    timings.prompt_ms covers only the computation. Including cached tokens in the
    numerator overstates prefill by 1/(1 - cached_share).
    """
    # 4 requests x 1000 prompt tokens, a quarter of them served from cache, each
    # reporting 1000 ms of prefill compute: 3000 computed tokens over 4.0 s.
    samples = [_sample(cached_tokens=250) for _ in range(4)]
    out = summarize(samples, wall_seconds=10.0, slots=2, ctx_per_slot=2048)
    assert out["prefill_tokens_computed"] == 3000
    assert out["prefill_tps"] == pytest.approx(750.0)


def test_summarize_rejects_a_run_with_no_prompt_accounting():
    """Absent prompt counts are not a clean run; they are no measurement at all."""
    samples = [_sample(prompt_tokens=0, cached_tokens=0, prompt_ms=0.0) for _ in range(4)]
    out = summarize(samples, wall_seconds=10.0, slots=2, ctx_per_slot=2048)
    assert out["prefill_valid"] is False
    assert out["prefill_tps"] is None


def test_summarize_tolerates_the_measured_cache_floor():
    """The chat template and llama.cpp block granularity cache ~13% at worst.

    Measured live on 2026-10-05 at 1000-token prompts. A threshold below this would
    mark every honest run invalid, which is the bug this test pins down.
    """
    floor = [_sample(cached_tokens=130) for _ in range(4)]  # 520 of 4000 = 13%
    assert summarize(floor, wall_seconds=10.0, slots=2, ctx_per_slot=2048)["prefill_valid"] is True


def test_summarize_percentile_fields_present():
    samples = [_sample(ttft_ms=float(i), latency_ms=float(i * 10)) for i in (1, 2, 3, 4)]
    out = summarize(samples, wall_seconds=10.0, slots=1, ctx_per_slot=2048)
    assert out["ttft_ms_p50"] == pytest.approx(2.5)
    assert out["latency_ms_p50"] == pytest.approx(25.0)
    assert out["ttft_ms_p95"] == pytest.approx(3.85)
    assert out["latency_ms_p95"] == pytest.approx(38.5)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_metrics.py -v` from `bench/`
Expected: collection error — `ModuleNotFoundError: No module named 'bench.metrics'`

- [ ] **Step 3: Write metrics.py**

Create `bench/bench/metrics.py`:

```python
"""Throughput and latency arithmetic over a set of completed requests.

Pure functions. The load generator collects samples; this turns them into the
numbers that go in the results file.
"""

from __future__ import annotations

from dataclasses import dataclass

# Above this share of prompt tokens served from llama.cpp's prefix cache, the
# measured prefill rate is not a measurement of prefill.
#
# 0.25 is calibrated, not guessed. Measured against the live server at 1000-token
# prompts on 2026-10-05: distinct prompts sit at 3-4% in isolation and reach ~13%
# across consecutive requests in one slot, because the chat template and llama.cpp's
# cache block granularity are an irreducible floor that no prompt design removes.
# Three identical prompts measured 68%. A 1% limit would therefore flag every honest
# run, while 0.25 clears the floor with headroom and still catches real prefix
# sharing by a factor of nearly three.
CACHE_CONTAMINATION_LIMIT = 0.25


@dataclass(frozen=True)
class RequestSample:
    ttft_ms: float
    latency_ms: float
    output_tokens: int
    prompt_tokens: int
    prompt_ms: float
    cached_tokens: int


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile. p is 0-100."""
    if not values:
        raise ValueError("percentile of an empty sample")
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"p must be 0-100, got {p}")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def summarize(
    samples: list[RequestSample],
    wall_seconds: float,
    slots: int,
    ctx_per_slot: int,
) -> dict:
    if not samples:
        raise ValueError("no samples to summarize")
    if wall_seconds <= 0:
        raise ValueError("wall_seconds must be positive")

    output_total = sum(s.output_tokens for s in samples)
    prompt_total = sum(s.prompt_tokens for s in samples)
    prompt_ms_total = sum(s.prompt_ms for s in samples)
    cached_total = sum(s.cached_tokens for s in samples)

    aggregate_tps = output_total / wall_seconds

    # Only the uncached tokens were actually computed, and timings.prompt_ms covers
    # only that computation. Dividing ALL prompt tokens by it inflates the rate by
    # 1/(1 - cached_share): a silent 1.33x even at the 25% share this still calls
    # valid, and 24x at the 99.9% share a shared-prefix bug once produced.
    computed_prompt_tokens = prompt_total - cached_total
    prefill_tps = (
        computed_prompt_tokens / (prompt_ms_total / 1000.0)
        if prompt_ms_total > 0 and computed_prompt_tokens > 0
        else None
    )

    # No prompt accounting means there is no prefill measurement to trust, so an
    # absent count is invalid rather than vacuously clean.
    contaminated = (
        prompt_total <= 0 or (cached_total / prompt_total) > CACHE_CONTAMINATION_LIMIT
    )

    return {
        "slots": slots,
        "ctx_per_slot": ctx_per_slot,
        "requests": len(samples),
        "wall_seconds": wall_seconds,
        "output_tokens_total": output_total,
        "prompt_tokens_total": prompt_total,
        # What was actually sent, not what was requested. The writeup quotes this,
        # because a requested prompt size is an estimate until the tokenizer sees it.
        "prompt_tokens_mean": prompt_total / len(samples),
        "aggregate_output_tps": aggregate_tps,
        "per_client_output_tps": aggregate_tps / slots,
        "prefill_tps": prefill_tps,
        "prefill_tokens_computed": computed_prompt_tokens,
        "cached_tokens_total": cached_total,
        "prefill_valid": not contaminated,
        "ttft_ms_p50": percentile([s.ttft_ms for s in samples], 50),
        "ttft_ms_p95": percentile([s.ttft_ms for s in samples], 95),
        "latency_ms_p50": percentile([s.latency_ms for s in samples], 50),
        "latency_ms_p95": percentile([s.latency_ms for s in samples], 95),
    }
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_metrics.py -v` from `bench/`
Expected: PASS, 8 passed.

- [ ] **Step 5: Write the failing load test**

Create `bench/tests/test_load.py`:

```python
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from bench import load
from bench.metrics import RequestSample


CHUNK_DELAY_S = 0.02
CHUNKS = 5


class _StubHandler(BaseHTTPRequestHandler):
    """Emits CHUNKS SSE deltas then a final chunk carrying usage and timings."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence the test output
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        assert body["stream"] is True
        assert body["ignore_eos"] is True

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write(payload: dict) -> None:
            data = f"data: {json.dumps(payload)}\n\n".encode()
            self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
            self.wfile.flush()

        import time

        for i in range(CHUNKS):
            time.sleep(CHUNK_DELAY_S)
            write({"choices": [{"delta": {"content": f"t{i} "}}]})

        write(
            {
                "choices": [{"delta": {}, "finish_reason": "length"}],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": CHUNKS,
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
                "timings": {"prompt_n": 1000, "prompt_ms": 500.0, "predicted_n": CHUNKS},
            }
        )
        data = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


@pytest.fixture
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _shares_long_run(a: str, b: str, run: int = 200) -> bool:
    """Does any `run`-character window of a appear anywhere in b?

    Every offset, not every `run`-th offset: a window-aligned scan misses a shared
    run straddling its boundaries. Short inputs compare whole.
    """
    if len(a) <= run or len(b) <= run:
        return a in b or b in a
    return any(a[i : i + run] in b for i in range(len(a) - run + 1))


def test_build_prompt_is_distinct_per_seed():
    a = load.build_prompt(0, 1000)
    b = load.build_prompt(1, 1000)
    assert a != b
    assert a[:50] != b[:50]


def test_build_prompt_shares_no_long_run_between_seeds():
    """The property that makes the prefill measurement real.

    A differing opening is not enough. Two prompts sharing a long body let
    llama.cpp serve almost the whole prefill from cache -- measured at 99.9%,
    inflating the reported prefill rate 24x.
    """
    a = load.build_prompt(0, 1000)
    b = load.build_prompt(1, 1000)
    assert not _shares_long_run(a, b)
    assert not _shares_long_run(b, a)


def test_build_prompt_is_deterministic():
    """The same sweep point must be rerunnable and comparable."""
    assert load.build_prompt(7, 1000) == load.build_prompt(7, 1000)


def test_build_prompt_of_different_sizes_shares_no_long_run():
    """A size change must not produce a prefix-extension of the smaller prompt.

    Seeding on the seed alone did exactly that, so re-running a sweep at a new
    --prompt-tokens value on a server that had not restarted was served 62.3% from
    the previous run's cache, rising to 99.9% on a repeat.
    """
    short = load.build_prompt(7, 600)
    long = load.build_prompt(7, 1000)
    assert not _shares_long_run(short, long)
    assert not long.startswith(short[:400])


def test_build_prompt_is_roughly_the_requested_length():
    prompt = load.build_prompt(0, 1000)
    # Sized by the measured 6.55 chars/token, so 1000 tokens is ~6550 characters.
    # The live check that this lands near 1000 real tokens is the server's tokenizer,
    # not this test; this only pins that the calibration is being applied at all.
    assert 6200 < len(prompt) < 6900


def test_one_request_measures_ttft_and_usage(stub_server):
    async def go():
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await load.one_request(
                client, stub_server, "stub-model", "hello", max_tokens=CHUNKS
            )

    sample = asyncio.run(go())
    assert sample.output_tokens == CHUNKS
    assert sample.prompt_tokens == 1000
    assert sample.prompt_ms == pytest.approx(500.0)
    assert sample.cached_tokens == 3
    # First delta arrives after one chunk delay; the whole stream takes CHUNKS of them.
    assert sample.ttft_ms >= CHUNK_DELAY_S * 1000 * 0.5
    assert sample.latency_ms > sample.ttft_ms


def test_run_slot_point_summarizes_all_clients(stub_server):
    out = asyncio.run(
        load.run_slot_point(
            base_url=stub_server,
            model="stub-model",
            slots=2,
            ctx_per_slot=2048,
            requests_per_client=3,
            prompt_tokens=100,
            max_tokens=CHUNKS,
        )
    )
    # 3 requests per client, first discarded as warm-up: 2 clients x 2 = 4 samples.
    assert out["requests"] == 4
    assert out["slots"] == 2
    assert out["output_tokens_total"] == 4 * CHUNKS
    assert out["prefill_valid"] is True

    # The window must be the two concurrent rounds, not the four requests end to
    # end. Four serial requests would take about 4 x CHUNKS x CHUNK_DELAY_S; two
    # concurrent rounds take about half that, so anything near the serial figure
    # means the clients were measured as if they had not overlapped.
    serial_s = 4 * CHUNKS * CHUNK_DELAY_S
    assert 0.0 < out["wall_seconds"] < serial_s * 0.8


def test_run_slot_point_window_excludes_a_straggler_tail(monkeypatch):
    """The window is the concurrent rounds, not first start to last finish.

    The stub server above gives both clients identical latency, so they advance in
    lockstep and every aggregation strategy agrees. Unequal clients are what
    separate them: letting each client run its own rounds lets the fast one finish
    early while the slow one generates alone, and spanning first start to last
    finish then divides both clients' tokens by a window that is mostly
    single-slot. That understates aggregate throughput, and it is the defect the
    round barrier fixes.

    Fast client 10 ms per request, slow client 100 ms, 3 rounds each with the first
    discarded. Round-synchronized: two rounds at the slow client's pace, 200 ms.
    First-start-to-last-finish would be about 290 ms, because the fast client's two
    measured requests land at 10-30 ms while the slow client's run to 300 ms.
    """
    latency_s = {0: 0.01, 1: 0.10}

    def fake_build_prompt(seed: int, approx_tokens: int) -> str:
        # run_slot_point builds prompts as build_prompt(index * 1000 + round, ...),
        # so the client index is recoverable and the fake can vary by client.
        return f"client={seed // 1000}"

    async def fake_one_request(client, base_url, model, prompt, max_tokens):
        index = int(prompt.split("=")[1])
        await asyncio.sleep(latency_s[index])
        return RequestSample(
            ttft_ms=1.0,
            latency_ms=latency_s[index] * 1000,
            output_tokens=max_tokens,
            prompt_tokens=1000,
            prompt_ms=1.0,
            cached_tokens=0,
        )

    monkeypatch.setattr(load, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(load, "one_request", fake_one_request)

    out = asyncio.run(
        load.run_slot_point(
            base_url="http://unused.invalid",
            model="stub",
            slots=2,
            ctx_per_slot=2048,
            requests_per_client=3,
            prompt_tokens=10,
            max_tokens=30,
        )
    )

    assert out["requests"] == 4
    assert out["wall_seconds"] == pytest.approx(0.20, abs=0.07)
    # Measured: the round barrier yields 0.226 s here, while the pre-fix structure
    # (each client running its own rounds, window = first start to last finish)
    # yields 0.305 s. The bound sits between them with room for event-loop
    # overhead on either side.
    assert out["wall_seconds"] < 0.27
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_load.py -v` from `bench/`
Expected: collection error — `ModuleNotFoundError: No module named 'bench.load'`

- [ ] **Step 7: Verify llama.cpp actually honours `ignore_eos` — BLOCKING**

`ignore_eos` is natively a llama.cpp `/completion` parameter, not an OpenAI field. The
OpenAI-compat layer at `/v1/chat/completions` forwards some extra fields and silently drops
others. If it drops this one, every request stops at EOS, output token counts vary, and the
sweep re-creates the exact defect the plan exists to avoid — with no error to notice.

Confirm the stack is up (`pwsh -NoProfile -File scripts/health.ps1`), then run:

```bash
curl -s http://hpz440:8080/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"local","messages":[{"role":"user","content":"Say hi."}],"max_tokens":300,"ignore_eos":true,"temperature":0}' > /tmp/eos.json
```

```bash
python -c "import json; d=json.load(open('/tmp/eos.json')); print(d['usage']['completion_tokens'], d['choices'][0]['finish_reason'])"
```

Expected if honoured: `300 length`. "Say hi." would naturally stop in a handful of tokens, so
300 proves EOS was ignored.

If it prints a small number and `stop`, the field was dropped. Then change `one_request` in
Step 8 to post to **`/completion`** instead — llama.cpp's native endpoint, which honours it —
using this payload shape:

```python
    # llama.cpp native endpoint. Streamed chunks are `data: {"content": "...", "stop": false}`;
    # the final chunk carries "timings", "tokens_predicted" and "tokens_evaluated" rather than
    # an OpenAI "usage" object.
    payload = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "ignore_eos": True,
        "stream": True,
        "temperature": 0.0,
        "cache_prompt": False,
    }
```

and read `tokens_predicted`, `tokens_evaluated`, and `timings.prompt_ms` from the final chunk.
`cache_prompt: False` exists only on this endpoint and removes the prefix-cache concern
outright — keep the distinct prompts anyway, and keep the `prefill_valid` check.

Record which endpoint you used in a comment at the top of `load.py`, and carry it into
`docs/cost-model.md` in Task 6.

- [ ] **Step 8: Write load.py**

Create `bench/bench/load.py`:

```python
"""Concurrent load generator for the llama.cpp OpenAI-compatible server.

One invocation measures one slot count. scripts/stress-test.ps1 owns the sweep,
the container restarts, and the GPU telemetry; this process only generates load
and prints a summary JSON object on stdout.

Three details decide whether the numbers mean anything:

* ignore_eos with a fixed max_tokens, so every request emits an identical token
  count. Without it you measure the model's verbosity.
* A prompt per client that shares no long run of text with any other, so llama.cpp's
  cache cannot serve one slot's prefill from another's. A varying head on a shared
  body fails this: measured 99.9% cached and a 24x inflated prefill rate.
* Streaming, so time to first token is observable at all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time

import httpx

from bench.metrics import RequestSample, summarize

# Ordinary words, so the tokenizer behaves as it would on real text; a repeated
# single character would not. The body is drawn from the seed rather than being a
# fixed string, which matters more than it looks: see build_prompt.
_WORDS = (
    "server model token latency cache prompt decode prefill throughput slot context "
    "window kernel memory bandwidth quantize weight tensor batch stream request reply "
    "inbox message draft classify archive journal policy gate agent briefing household "
    "electricity meter amortize capex median listing provider hosted rented owned"
).split()

# Measured on this model's tokenizer via the server's /tokenize endpoint on
# 2026-10-05: 6.21 chars/token at 250 requested tokens, settling to 6.56-6.58 from
# 1000 upward. The naive 4.0 used before made --prompt-tokens 1000 send only 610
# tokens, a 39% undershoot that would have mislabelled every row of the writeup.
_CHARS_PER_TOKEN = 6.55


def build_prompt(seed: int, approx_tokens: int) -> str:
    """A prompt of ~approx_tokens tokens sharing no long run of text with any other seed.

    Every word comes from the seed, not just an opening line. A varying head on a
    fixed body is NOT enough, and the difference is not subtle: measured against this
    server on 2026-10-05, prompts built that way were served 99.9% from llama.cpp's
    cache across two clients and reported a prefill rate of 55,934 tok/s against a
    real 2,340 -- a 24x fiction. Seed-derived bodies measured 4.2% cached.

    Deterministic in the seed, so a rerun of the same sweep point is comparable.
    """
    # Both parameters seed the generator, as a string: a tuple seed raises TypeError
    # on current Python, while str seeding is supported and deterministic across
    # processes. Seeding on `seed` alone makes a longer
    # prompt a literal prefix-extension of a shorter one at the same seed, so a run
    # at a new --prompt-tokens value is served from the previous run's cache on a
    # server that has not restarted: measured 62.3% cached, then 99.9% on a repeat.
    rng = random.Random(f"{seed}:{approx_tokens}")
    target_chars = int(approx_tokens * _CHARS_PER_TOKEN)
    parts = [f"Note {rng.randrange(10 ** 9)}. Summarize these notes."]
    size = len(parts[0])
    while size < target_chars:
        word = rng.choice(_WORDS)
        parts.append(word)
        size += len(word) + 1
    return " ".join(parts)[:target_chars]


async def one_request(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> RequestSample:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "ignore_eos": True,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.0,
    }

    started = time.perf_counter()
    ttft: float | None = None
    usage: dict = {}
    timings: dict = {}
    deltas = 0

    async with client.stream(
        "POST", f"{base_url}/v1/chat/completions", json=payload
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            chunk = line[len("data: ") :].strip()
            if chunk == "[DONE]":
                break
            event = json.loads(chunk)
            choices = event.get("choices") or []
            if choices and (choices[0].get("delta") or {}).get("content"):
                deltas += 1
                if ttft is None:
                    ttft = (time.perf_counter() - started) * 1000.0
            if event.get("usage"):
                usage = event["usage"]
            if event.get("timings"):
                timings = event["timings"]

    latency_ms = (time.perf_counter() - started) * 1000.0
    if ttft is None:
        raise RuntimeError("stream produced no content deltas")

    output_tokens = int(usage.get("completion_tokens") or timings.get("predicted_n") or deltas)
    prompt_tokens = int(usage.get("prompt_tokens") or timings.get("prompt_n") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)

    return RequestSample(
        ttft_ms=ttft,
        latency_ms=latency_ms,
        output_tokens=output_tokens,
        prompt_tokens=prompt_tokens,
        prompt_ms=float(timings.get("prompt_ms") or 0.0),
        cached_tokens=cached,
    )


async def run_slot_point(
    base_url: str,
    model: str,
    slots: int,
    ctx_per_slot: int,
    requests_per_client: int,
    prompt_tokens: int,
    max_tokens: int,
) -> dict:
    """Drive `slots` concurrent clients and summarize the measured requests.

    Each client's first request is discarded as warm-up, so the returned sample
    count is slots * (requests_per_client - 1).
    """
    if requests_per_client < 2:
        raise ValueError("requests_per_client must be at least 2 (one is warm-up)")

    collected: list[RequestSample] = []
    round_spans: list[tuple[float, float]] = []

    async def one(
        index: int, round_index: int, client: httpx.AsyncClient
    ) -> tuple[RequestSample, float, float]:
        prompt = build_prompt(index * 1000 + round_index, prompt_tokens)
        started = time.perf_counter()
        sample = await one_request(client, base_url, model, prompt, max_tokens)
        return sample, started, time.perf_counter()

    # Separate clients so each concurrent stream gets its own connection.
    clients = [httpx.AsyncClient(timeout=httpx.Timeout(600.0)) for _ in range(slots)]
    try:
        # One round at a time, all slots together. Letting each client run its own
        # rounds independently leaves the slowest client finishing alone while the
        # others idle, and that solo tail lands inside the measured window and
        # understates aggregate throughput -- worst when there are few rounds.
        # Gathering per round keeps every measured window genuinely concurrent.
        for round_index in range(requests_per_client):
            results = await asyncio.gather(
                *(one(i, round_index, clients[i]) for i in range(slots))
            )
            if round_index == 0:
                continue  # warm-up round, measured by nobody
            collected.extend(sample for sample, _, _ in results)
            round_spans.append(
                (
                    min(started for _, started, _ in results),
                    max(finished for _, _, finished in results),
                )
            )
    finally:
        await asyncio.gather(*(c.aclose() for c in clients), return_exceptions=True)

    if not round_spans:
        raise RuntimeError("no measured requests completed")
    # Sum the per-round concurrent windows, so the gaps between rounds are not
    # counted as time the server spent generating.
    measured_wall_s = sum(end - start for start, end in round_spans)
    return summarize(collected, measured_wall_s, slots, ctx_per_slot)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One slot-count load point.")
    parser.add_argument("--base-url", default="http://hpz440:8080")
    parser.add_argument("--model", required=True, help="llama.cpp container model path")
    parser.add_argument("--slots", type=int, required=True)
    parser.add_argument("--ctx-per-slot", type=int, required=True)
    parser.add_argument("--requests-per-client", type=int, default=5)
    parser.add_argument("--prompt-tokens", type=int, default=1000)
    parser.add_argument("--max-tokens", type=int, default=300)
    args = parser.parse_args(argv)

    result = asyncio.run(
        run_slot_point(
            base_url=args.base_url,
            model=args.model,
            slots=args.slots,
            ctx_per_slot=args.ctx_per_slot,
            requests_per_client=args.requests_per_client,
            prompt_tokens=args.prompt_tokens,
            max_tokens=args.max_tokens,
        )
    )
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 9: Run the whole suite to verify it passes**

Run: `uv run pytest -v` from `bench/`
Expected: PASS, 39 passed (11 in `test_cost.py`, 10 in `test_prices.py`, 10 in `test_metrics.py`, 8 in `test_load.py`).

Then confirm against the live server that `--prompt-tokens 1000` now sends close to 1000
tokens, since that is the claim the writeup makes:

```
uv run python -m bench.load --base-url http://hpz440:8080 --model /models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --slots 2 --ctx-per-slot 2048 --requests-per-client 3 --prompt-tokens 1000 --max-tokens 60
```

Restart `llm-api` first so the check starts from a cold cache, the way each sweep point
does:

```
docker --context hpz440 compose --env-file .env restart llm-api
```

Expected: `prompt_tokens_mean` within about 5% of 1000, `prefill_valid: true`, and
`cached_tokens_total` a low single-digit percentage of `prompt_tokens_total`.

A warm server can legitimately report a high cached share when an earlier run happened to
send overlapping prompts; that is why each sweep point in Task 5 restarts the container
before measuring, and why this check does too.

If `test_one_request_measures_ttft_and_usage` fails on `ttft_ms`, the stub's chunked framing is at fault, not `load.py` — check that each SSE event is written as its own HTTP chunk and flushed.

If Step 7 forced the `/completion` endpoint, update `_StubHandler` and
`test_one_request_measures_ttft_and_usage` to the native chunk shape in the same step. The test
must match the endpoint the implementation actually calls.

- [ ] **Step 10: Commit**

```bash
git add bench/bench/metrics.py bench/bench/load.py bench/tests/test_metrics.py bench/tests/test_load.py
git commit -m "feat(bench): concurrent streaming load generator and metrics"
```

---

### Task 5: Sweep orchestration

The PowerShell wrapper owns everything that touches the server: `.env` rewriting, container restarts, GPU telemetry, and the restore. It must restore `.env` even on Ctrl+C, because leaving `LLM_CONTEXT_SIZE` at 16384 would silently change Jarvis's token budget.

**Files:**
- Create: `scripts/stress-test.ps1`
- Modify: `tests/assert-script-contracts.ps1`
- Modify: `tests/assert-project-shape.ps1`

**Interfaces:**
- Consumes: `bench/bench/load.py`'s CLI — `uv run python -m bench.load --base-url --model --slots --ctx-per-slot --requests-per-client --prompt-tokens --max-tokens`, printing one JSON object on stdout.
- Produces: `benchmarks/stress-<stamp>.json`, an object `{ "started", "model", "ctx_per_slot", "price_per_kwh", "capex_usd", "points": [ <summarize dict merged with gpu_watts_* and vram_mb_max> ] }`.

- [ ] **Step 1: Write the failing contract assertions**

Append to `tests/assert-script-contracts.ps1`:

```powershell
Assert-FileContains 'scripts/stress-test.ps1' 'LLM_PARALLEL'
Assert-FileContains 'scripts/stress-test.ps1' 'hpz440:8080'
Assert-FileContains 'scripts/stress-test.ps1' 'finally'
Assert-FileContains 'scripts/stress-test.ps1' 'bench\.load'
Assert-FileContains 'scripts/stress-test.ps1' 'ignore the prefill'
Assert-FileNotContains 'scripts/stress-test.ps1' 'localhost:8080'
```

Append to `tests/assert-project-shape.ps1`, before the `$Gitkeep` block:

```powershell
Assert-FileContains 'README.md' 'scripts/stress-test\.ps1'
Assert-FileContains 'docs/operations.md' 'scripts/stress-test\.ps1'
```

- [ ] **Step 2: Run both to verify they fail**

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: FAIL with `Missing file: scripts/stress-test.ps1`

- [ ] **Step 3: Write the wrapper**

Create `scripts/stress-test.ps1`:

```powershell
<#
Concurrency sweep for the llama.cpp server on the HPZ440.

For each slot count it rewrites .env, restarts llm-api, samples GPU power in a
throwaway container, runs bench/load.py against http://hpz440:8080, and merges
the results. .env is restored byte-for-byte in the finally block, including on
Ctrl+C -- LLM_CONTEXT_SIZE also feeds JARVIS_CONTEXT_TOKENS, so leaving it
raised would silently change Jarvis's budget.

Jarvis is unavailable while this runs. The sweep takes several minutes.
#>
[CmdletBinding()]
param(
    [int[]]$Slots = @(1, 2, 4, 8),
    [int]$CtxPerSlot = 2048,
    [int]$RequestsPerClient = 5,
    [int]$PromptTokens = 1000,
    [int]$MaxTokens = 300,
    [int]$IdleSampleSeconds = 20
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }
$ModelMatch = Select-String -Path $EnvPath -Pattern '^LLM_MODEL_PATH=(.+)$'
if (-not $ModelMatch) { throw 'LLM_MODEL_PATH missing from .env.' }
$Model = $ModelMatch.Matches.Groups[1].Value

$BaseUrl = 'http://hpz440:8080'
$CudaImage = 'nvidia/cuda:12.4.1-base-ubuntu22.04'
$SmiQuery = 'power.draw,utilization.gpu,memory.used'

# Byte-for-byte backup so the restore cannot reformat the operator's file.
$OriginalEnv = [System.IO.File]::ReadAllBytes($EnvPath)

function Set-EnvKey {
    param([string]$Name, [string]$Value)
    $Lines = Get-Content $EnvPath
    if ($Lines | Where-Object { $_ -match "^$Name=" }) {
        $Lines = $Lines | ForEach-Object { if ($_ -match "^$Name=") { "$Name=$Value" } else { $_ } }
    } else {
        $Lines += "$Name=$Value"
    }
    Set-Content -Path $EnvPath -Value $Lines
}

# The sampler runs unbounded and is killed explicitly, so it always outlives the load. A
# guessed timeout would expire mid-load at high slot counts and report watts from a partial
# window.
$SamplerName = 'hpz440-bench-smi'

function Start-GpuSampler {
    docker --context $Context rm -f $SamplerName 2>$null | Out-Null
    Start-Job -ScriptBlock {
        param($Ctx, $Image, $Query, $Name)
        docker --context $Ctx run --rm --name $Name --gpus all $Image `
            nvidia-smi --query-gpu=$Query --format=csv,noheader,nounits -l 1
    } -ArgumentList $Context, $CudaImage, $SmiQuery, $SamplerName
}

function Stop-GpuSampler {
    param($Job)
    # Killing the container ends the piped process, which completes the job.
    docker --context $Context kill $SamplerName 2>$null | Out-Null
    $Lines = Receive-Job -Job $Job -Wait -AutoRemoveJob 2>$null
    $Watts = @(); $Vram = @()
    foreach ($Line in $Lines) {
        $Parts = ($Line -split ',') | ForEach-Object { $_.Trim() }
        if ($Parts.Count -ge 3 -and $Parts[0] -match '^[\d.]+$') {
            $Watts += [double]$Parts[0]
            $Vram += [double]$Parts[2]
        }
    }
    if ($Watts.Count -eq 0) { return $null }
    [pscustomobject]@{
        mean = [math]::Round(($Watts | Measure-Object -Average).Average, 2)
        max  = [math]::Round(($Watts | Measure-Object -Maximum).Maximum, 2)
        vram = [math]::Round(($Vram | Measure-Object -Maximum).Maximum, 0)
        n    = $Watts.Count
    }
}

function Wait-ForModel {
    param([int]$TimeoutSeconds = 180)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        try {
            Invoke-RestMethod -Uri "$BaseUrl/v1/models" -Method Get -TimeoutSec 5 | Out-Null
            return $true
        } catch { Start-Sleep -Seconds 3 }
    }
    return $false
}

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutputDir = Join-Path $Root 'benchmarks'
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$OutputPath = Join-Path $OutputDir "stress-$Stamp.json"
$Points = @()

# Baseline draw with the model resident in VRAM and no requests in flight. This is NOT a
# cold-idle GPU -- llama.cpp holds the weights, and that is the state the box actually sits in
# 24/7, which is the right number for the cost model. docs/cost-model.md labels it so.
Write-Host "Sampling baseline GPU power (model resident, no load) for $IdleSampleSeconds s..."
$IdleSampler = Start-GpuSampler
Start-Sleep -Seconds $IdleSampleSeconds
$IdleStats = Stop-GpuSampler $IdleSampler
if ($null -eq $IdleStats) {
    Write-Warning 'GPU telemetry unavailable. Throughput will still be measured; docs/cost-model.md cannot be regenerated without watts.'
}

try {
    foreach ($N in $Slots) {
        $TotalCtx = $N * $CtxPerSlot
        Write-Host ""
        Write-Host "=== $N slot(s), $CtxPerSlot ctx each (total $TotalCtx) ==="
        Set-EnvKey -Name 'LLM_PARALLEL' -Value "$N"
        Set-EnvKey -Name 'LLM_CONTEXT_SIZE' -Value "$TotalCtx"

        docker --context $Context compose --env-file .env up -d llm-api
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "llm-api failed to start at $N slots (likely out of VRAM). Recording oom and continuing."
            $Points += [pscustomobject]@{ slots = $N; ctx_per_slot = $CtxPerSlot; status = 'oom' }
            continue
        }
        if (-not (Wait-ForModel)) {
            Write-Warning "llm-api did not answer /v1/models at $N slots. Recording unhealthy and stopping the sweep."
            $Points += [pscustomobject]@{ slots = $N; ctx_per_slot = $CtxPerSlot; status = 'unhealthy' }
            break
        }

        $Sampler = Start-GpuSampler
        $Json = & uv --directory (Join-Path $Root 'bench') run python -m bench.load `
            --base-url $BaseUrl --model $Model --slots $N --ctx-per-slot $CtxPerSlot `
            --requests-per-client $RequestsPerClient --prompt-tokens $PromptTokens `
            --max-tokens $MaxTokens
        $LoadExit = $LASTEXITCODE
        $LoadStats = Stop-GpuSampler $Sampler

        if ($LoadExit -ne 0) {
            Write-Warning "Load generator failed at $N slots (exit $LoadExit). Recording error and continuing."
            $Points += [pscustomobject]@{ slots = $N; ctx_per_slot = $CtxPerSlot; status = 'error' }
            continue
        }

        $Point = $Json | ConvertFrom-Json
        $Point | Add-Member -NotePropertyName status -NotePropertyValue 'ok'
        $Point | Add-Member -NotePropertyName gpu_watts_idle -NotePropertyValue $(if ($IdleStats) { $IdleStats.mean } else { $null })
        $Point | Add-Member -NotePropertyName gpu_watts_mean -NotePropertyValue $(if ($LoadStats) { $LoadStats.mean } else { $null })
        $Point | Add-Member -NotePropertyName gpu_watts_max -NotePropertyValue $(if ($LoadStats) { $LoadStats.max } else { $null })
        $Point | Add-Member -NotePropertyName vram_mb_max -NotePropertyValue $(if ($LoadStats) { $LoadStats.vram } else { $null })
        $Points += $Point

        Write-Host ("  aggregate {0:N1} tok/s, per-client {1:N1} tok/s, TTFT p95 {2:N0} ms, {3} W mean" -f `
            $Point.aggregate_output_tps, $Point.per_client_output_tps, $Point.ttft_ms_p95, $Point.gpu_watts_mean)
        if (-not $Point.prefill_valid) {
            Write-Warning "  Prefix cache served $($Point.cached_tokens_total) prompt tokens at $N slots -- ignore the prefill rate for this point."
        }
    }
}
finally {
    Write-Host ""
    Write-Host 'Restoring .env and restarting llm-api at production settings...'
    [System.IO.File]::WriteAllBytes($EnvPath, $OriginalEnv)
    docker --context $Context rm -f $SamplerName 2>$null | Out-Null
    docker --context $Context compose --env-file .env up -d llm-api
    if ($LASTEXITCODE -ne 0) { Write-Warning 'llm-api did not restart cleanly. Run scripts/start.ps1.' }
}

@{
    started       = $Stamp
    model         = $Model
    ctx_per_slot  = $CtxPerSlot
    prompt_tokens = $PromptTokens
    max_tokens    = $MaxTokens
    capex_usd     = 300.0
    price_per_kwh = 0.17
    gpu_watts_idle = $(if ($IdleStats) { $IdleStats.mean } else { $null })
    points        = $Points
} | ConvertTo-Json -Depth 12 | Set-Content -Path $OutputPath

Write-Host "Sweep written to $OutputPath"
Write-Host "Next: uv --directory bench run python -m bench.report --sweep $OutputPath"
```

- [ ] **Step 4: Add the two doc lines the project-shape test now demands**

In `README.md`, in the command list alongside the other `scripts/*.ps1` entries, add:

```
pwsh -NoProfile -File scripts/stress-test.ps1   # concurrency sweep; rewrites and restores .env, Jarvis is down while it runs
```

In `docs/operations.md`, near the `scripts/benchmark.ps1` material, add:

```markdown
### Concurrency sweep

`pwsh -NoProfile -File scripts/stress-test.ps1` measures aggregate throughput at 1, 2, 4, and
8 llama.cpp slots, holding 2048 tokens of context per slot. It rewrites `LLM_PARALLEL` and
`LLM_CONTEXT_SIZE` in `.env`, restarts `llm-api` once per slot count, and restores `.env`
byte-for-byte in a `finally` block. Jarvis shares `LLM_CONTEXT_SIZE`, so Jarvis is
unavailable for the few minutes the sweep runs. Unlike the other scripts it talks to
`http://hpz440:8080` directly rather than `localhost`, because an SSH tunnel would become the
bottleneck at eight concurrent streams.
```

- [ ] **Step 5: Run both test scripts to verify they pass**

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: PASS

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: PASS, `Project guardrail checks passed.`

- [ ] **Step 6: Smoke-test the restore path without a full sweep**

Record the current `.env` hash, run a one-point sweep, and confirm the file comes back identical:

```bash
sha256sum .env
```

Run: `pwsh -NoProfile -File scripts/stress-test.ps1 -Slots 1 -RequestsPerClient 2 -IdleSampleSeconds 5`

```bash
sha256sum .env
```

Expected: the two hashes match exactly, and `benchmarks/stress-<stamp>.json` exists with one point whose `status` is `ok`.

Then confirm Jarvis recovered:

Run: `pwsh -NoProfile -File scripts/health.ps1`
Expected: all three endpoints answer.

- [ ] **Step 7: Commit**

```bash
git add scripts/stress-test.ps1 tests/assert-script-contracts.ps1 tests/assert-project-shape.ps1 README.md docs/operations.md
git commit -m "feat: concurrency sweep script with .env restore and GPU power sampling"
```

---

### Task 6: Run the sweep and write the comparison

This is the task that produces the answer. It needs the GPU and a healthy stack.

**Files:**
- Create: `bench/bench/report.py`
- Create: `bench/tests/test_report.py`
- Create: `docs/cost-model.md`
- Modify: `docs/models.md`
- Modify: `tests/assert-project-shape.ps1`
- Modify: `docs/superpowers/specs/2026-10-04-stress-test-cost-model-design.md` (Status line)

**Interfaces:**
- Consumes: `bench.cost` (all functions listed in Task 2), `bench.prices.load_prices`, and a sweep JSON of the shape Task 5 produces.
- Produces, in `bench/bench/report.py`:
  - `def throughput_rows(sweep: dict) -> list[dict]` — one row per `ok` point
  - `def break_even_rows(sweep: dict, hosted: list[HostedPrice], hours_active_options: list[float]) -> list[dict]`
  - `def main(argv: list[str] | None = None) -> int` — `--sweep <path>` prints both Markdown tables on stdout

- [ ] **Step 1: Write the failing report test**

Create `bench/tests/test_report.py`:

```python
import pytest

from bench import report
from bench.prices import HostedPrice


SWEEP = {
    "model": "/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    "ctx_per_slot": 2048,
    "capex_usd": 300.0,
    "price_per_kwh": 0.17,
    "gpu_watts_idle": 12.0,
    "points": [
        {
            "status": "ok",
            "slots": 1,
            "ctx_per_slot": 2048,
            "aggregate_output_tps": 62.0,
            "per_client_output_tps": 62.0,
            "prefill_tps": 850.0,
            "prefill_valid": True,
            "ttft_ms_p50": 1200.0,
            "ttft_ms_p95": 1400.0,
            "latency_ms_p50": 5000.0,
            "latency_ms_p95": 5200.0,
            "gpu_watts_mean": 170.0,
            "vram_mb_max": 5600,
        },
        {"status": "oom", "slots": 8, "ctx_per_slot": 2048},
    ],
}

HOSTED = [
    HostedPrice(
        provider="ExampleHost",
        model="Llama-3.1-8B-Instruct",
        usd_per_mtok_in=0.20,
        usd_per_mtok_out=0.20,
        source_url="https://example.invalid/pricing",
        retrieved="2026-10-04",
    )
]


def test_throughput_rows_skips_failed_points():
    rows = report.throughput_rows(SWEEP)
    assert len(rows) == 1
    assert rows[0]["slots"] == 1
    assert rows[0]["aggregate_output_tps"] == pytest.approx(62.0)


def test_break_even_uses_peak_watts_from_the_sweep():
    rows = report.break_even_rows(SWEEP, HOSTED, hours_active_options=[60.0])
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "ExampleHost"
    assert row["hours_active"] == pytest.approx(60.0)
    # 12 W idle, 170 W load, 60 h active, $0.17/kWh, $300/36 mo => $11.4137/mo.
    assert row["monthly_cost_usd"] == pytest.approx(11.4137, abs=1e-3)
    assert row["hosted_per_mixed_mtok"] == pytest.approx(0.20)
    assert row["break_even_mixed_mtok"] == pytest.approx(57.0685, abs=1e-2)
    # 57.0685 Mmix x 769.23 requests/Mmix
    assert row["break_even_requests_per_month"] == pytest.approx(43899, rel=1e-3)


def test_break_even_raises_without_watts():
    broken = {**SWEEP, "gpu_watts_idle": None}
    with pytest.raises(ValueError, match="watts"):
        report.break_even_rows(broken, HOSTED, hours_active_options=[60.0])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_report.py -v` from `bench/`
Expected: collection error — `ModuleNotFoundError: No module named 'bench.report'`

- [ ] **Step 3: Write report.py**

Create `bench/bench/report.py`:

```python
"""Turn a sweep JSON plus the price file into the Markdown tables for the docs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench import cost
from bench.prices import HostedPrice, load_prices

HOURS_ACTIVE_OPTIONS = [30.0, 100.0, 300.0, 720.0]


def throughput_rows(sweep: dict) -> list[dict]:
    """One row per successfully measured slot count."""
    return [p for p in sweep.get("points", []) if p.get("status") == "ok"]


def _peak_load_watts(sweep: dict) -> float:
    watts = [
        p["gpu_watts_mean"]
        for p in throughput_rows(sweep)
        if p.get("gpu_watts_mean") is not None
    ]
    if not watts:
        raise ValueError("sweep has no gpu_watts_mean; cannot model cost without watts")
    return max(watts)


def break_even_rows(
    sweep: dict,
    hosted: list[HostedPrice],
    hours_active_options: list[float] | None = None,
) -> list[dict]:
    idle = sweep.get("gpu_watts_idle")
    if idle is None:
        raise ValueError("sweep has no gpu_watts_idle; cannot model cost without watts")
    load_watts = _peak_load_watts(sweep)
    capex = float(sweep.get("capex_usd", cost.CAPEX_USD))
    kwh = float(sweep.get("price_per_kwh", cost.PRICE_PER_KWH))
    options = hours_active_options or HOURS_ACTIVE_OPTIONS
    per_mmix_requests = cost.requests_per_mixed_mtok()

    rows: list[dict] = []
    for hours in options:
        monthly = cost.monthly_cost_of_ownership(
            capex,
            watts_idle=float(idle),
            watts_load=load_watts,
            hours_active=hours,
            price_per_kwh=kwh,
        )
        for price in hosted:
            per_mmix = cost.hosted_cost_per_mixed_mtok(
                price.usd_per_mtok_in, price.usd_per_mtok_out
            )
            mmix = cost.break_even_mixed_mtok(monthly, per_mmix)
            rows.append(
                {
                    "provider": price.provider,
                    "model": price.model,
                    "hours_active": hours,
                    "monthly_cost_usd": monthly,
                    "hosted_per_mixed_mtok": per_mmix,
                    "break_even_mixed_mtok": mmix,
                    "break_even_requests_per_month": mmix * per_mmix_requests,
                    "source_url": price.source_url,
                    "retrieved": price.retrieved,
                }
            )
    return rows


def _throughput_table(sweep: dict) -> str:
    lines = [
        "| Slots | Ctx/slot | Prompt tok | Aggregate tok/s | Per-client tok/s | Prefill tok/s | TTFT p50 | TTFT p95 | GPU W mean | VRAM MB |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in throughput_rows(sweep):
        prefill = f"{p['prefill_tps']:.0f}" if p.get("prefill_valid") else "n/a (cached)"
        lines.append(
            f"| {p['slots']} | {p['ctx_per_slot']} | {p.get('prompt_tokens_mean', 0):.0f} | "
            f"{p['aggregate_output_tps']:.1f} | "
            f"{p['per_client_output_tps']:.1f} | {prefill} | {p['ttft_ms_p50']:.0f} ms | "
            f"{p['ttft_ms_p95']:.0f} ms | {p.get('gpu_watts_mean')} | {p.get('vram_mb_max')} |"
        )
    return "\n".join(lines)


def _break_even_table(rows: list[dict]) -> str:
    lines = [
        "| Provider / model | Active h/month | Owning $/month | Hosted $/mixed Mtok | Break-even Mtok/month | Break-even requests/month |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['provider']} {r['model']} | {r['hours_active']:.0f} | "
            f"${r['monthly_cost_usd']:.2f} | ${r['hosted_per_mixed_mtok']:.4f} | "
            f"{r['break_even_mixed_mtok']:.1f} | {r['break_even_requests_per_month']:,.0f} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown tables from a sweep.")
    parser.add_argument("--sweep", required=True)
    parser.add_argument("--prices", default=str(Path(__file__).resolve().parent / "prices.json"))
    args = parser.parse_args(argv)

    sweep = json.loads(Path(args.sweep).read_text(encoding="utf-8"))
    hosted, _hardware = load_prices(args.prices)

    print("## Throughput\n")
    print(_throughput_table(sweep))
    print("\n## Break-even\n")
    print(_break_even_table(break_even_rows(sweep, hosted)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -v` from `bench/`
Expected: PASS, zero failures.

- [ ] **Step 5: Commit the report module before the hardware run**

```bash
git add bench/bench/report.py bench/tests/test_report.py
git commit -m "feat(bench): Markdown report tables for throughput and break-even"
```

- [ ] **Step 6: Run the real sweep**

Confirm the stack is healthy first:

Run: `pwsh -NoProfile -File scripts/health.ps1`
Expected: all three endpoints answer.

Then:

Run: `pwsh -NoProfile -File scripts/stress-test.ps1`

Expected: four `=== N slot(s) ===` blocks, each printing aggregate tok/s and mean watts, then `Restoring .env...`, then `Sweep written to benchmarks/stress-<stamp>.json`.

If the 8-slot point reports `oom`, that is a real result — record it rather than retrying at a smaller context. If any point warns about the prefix cache, `build_prompt` is not producing distinct enough prompts; fix `load.py` and re-run before writing the docs.

Verify `.env` survived:

```bash
grep -E '^(LLM_PARALLEL|LLM_CONTEXT_SIZE)=' .env
```

Expected: `LLM_PARALLEL=1` and `LLM_CONTEXT_SIZE=8192`.

- [ ] **Step 7: Generate the tables**

Run: `uv --directory bench run python -m bench.report --sweep benchmarks/stress-<stamp>.json`

Expected: two Markdown tables on stdout. Keep the output; it goes into the two docs verbatim.

- [ ] **Step 8: Append the sweep rows to docs/models.md**

Add one row per measured slot count to the existing Measured table in `docs/models.md`, after the two existing rows. Use the real numbers from Step 7. The `Context` column holds the **total** context, and the Notes column must state the slot count and that per-slot context is 2048:

```markdown
| Qwen2.5-7B-Instruct | Q4_K_M | 2048 | <N> | 2026-10-04 | 1 slot. Sweep baseline, 2048 ctx/slot, 1000-token prompts, 300 tokens with ignore_eos. `benchmarks/stress-<stamp>.json`. |
```

Then add a short paragraph under the table:

```markdown
Concurrency: `scripts/stress-test.ps1` measured aggregate throughput at 1, 2, 4, and 8 slots
with 2048 tokens of context each. See `docs/cost-model.md` for the full table and what it
means for the economics. The single-slot rows above at context 4096 and 8192 are not directly
comparable to the sweep rows, which all run at 2048 per slot.
```

- [ ] **Step 9: Write docs/cost-model.md**

Create `docs/cost-model.md` with this structure, filling every number from Step 7's output and `bench/prices.json`:

````markdown
# Cost Model: When Does the HPZ440 Beat a Hosted Model?

Measured 2026-10-04 on the RTX 3060 12GB with Qwen2.5-7B-Instruct Q4_K_M.
Source data: `benchmarks/stress-<stamp>.json`. Regenerate with
`uv --directory bench run python -m bench.report --sweep <file>`.

## The question

"Tokens per dollar of hardware" is unbounded for a box you already own — run it longer and
the figure improves without limit. The decision-relevant form is the break-even volume: the
monthly token volume at which paying a hosted provider costs the same as amortized hardware
plus electricity.

## Assumptions

| Input | Value | Source |
| --- | --- | --- |
| Capex | $300 | RTX 3060 12GB, purchased 2026-09-29 |
| Amortization | 36 months | Assumption |
| Electricity | $0.17/kWh | Conrad's rate, 2026-10 |
| Powered hours | 720/month | The HPZ440 stays on |
| Token mix | 1000 in / 300 out per request | Jarvis triage shape: a message body in, a short classification out |
| Baseline GPU draw, model resident | <N> W | Measured, `nvidia-smi`, weights loaded, no requests in flight. The state the box sits in 24/7, not a cold-idle card |
| Load GPU draw | <N> W | Measured, peak sweep mean |
| Endpoint | `/v1/chat/completions` or `/completion` | Whichever honoured `ignore_eos`; see Task 4 Step 7 |

## Throughput

<the throughput table from Step 7>

Percentiles are over `slots x 4` measured requests (5 per client, the first discarded as
warm-up). At 1 slot that is 4 samples, so read the 1-slot p95 as the slowest of four requests,
not as a tail latency.

Every row's prefill figure carries a cache check: each client sends a distinct prompt, and the
run records what share of prompt tokens llama.cpp served from its prefix cache instead of
computing. Measured on this server, distinct prompts leave a 3-13% irreducible floor -- the
chat template plus the cache's block granularity -- while identical prompts reach 68%. So a row
reporting `prefill_valid: false` means the prompts really did share a prefix and that row's
prefill number should be ignored. Say for each row whether the check passed.

<One paragraph: did throughput scale with slots, and where did it stop scaling? If the 8-slot
point OOMed or regressed, say so and give the number.>

## Break-even

<the break-even table from Step 7>

<One paragraph naming the headline figure: at Jarvis's actual load, which side wins, and by
how much.>

## What this does not say

- **GPU-only watts.** `nvidia-smi` reports the card, not the HP Z440 around it. Whole-box
  draw is materially higher, so the owning cost above is a **lower bound** and the real
  break-even volume is **higher** than the table says. A wall meter would close this.
- **The baseline is not a cold-idle GPU.** It is measured with the model resident in VRAM,
  because that is how the box runs. A card with no model loaded would draw less.
- **Quality is not matched to frontier models.** Every hosted row is a Llama-3.1-8B or
  Qwen-7B-class instruct model — the same tier as what runs here. Frontier APIs are excluded
  on purpose: quoting their $/Mtok beside a 7B's throughput would be a comparison of two
  different things.
- **Local-hardware rows are published figures, not measured here.** Only the RTX 3060 row in
  `bench/prices.json` has `measured_here: true`.
- **Hosted prices move.** Every price in `bench/prices.json` carries the URL it came from and
  the date it was read. Re-read them before relying on this.
- **Non-price reasons are not modelled.** Mail staying on the LAN, no per-token metering, and
  no dependency on someone else's uptime are the reasons this box exists. They do not appear
  in a dollar figure.

## Hardware comparison

<A table from bench/bench/prices.json's hardware entries, one row each: name, price, how to
read that price (`price_note`), published 7B Q4 decode tok/s, tok/s per dollar, and BOTH
citations -- `price_source` for the price and `benchmark_source` for the throughput figure.
Mark the 3060 row as the measured one. Leave the tok/s and tok/s-per-dollar cells empty for any
row whose `decode_tps_7b_q4` is null rather than filling them with an estimate.>

State plainly under that table which items could not be sourced and why, so a reader does not
mistake the list for the whole market. As of 2026-10-05 that was Groq (no public price for a
Llama-3.1-8B-class model) and the Mac mini M4 (discontinued from Apple's own storefront, with
third-party listings spanning $449-$1099 and no defensible single figure).
````

- [ ] **Step 10: Add the doc assertions and run the tests**

Append to `tests/assert-project-shape.ps1`, before the `$Gitkeep` block:

```powershell
Assert-FileContains 'docs/cost-model.md' '^# Cost Model'
Assert-FileContains 'docs/cost-model.md' 'lower bound'
Assert-FileContains 'docs/cost-model.md' 'Break-even'
Assert-FileContains 'docs/models.md' 'Concurrency'
```

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: PASS

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: PASS

Run: `uv run pytest -v` from `bench/`
Expected: PASS, zero failures.

Run: `uv run pytest` from `jarvis/`
Expected: PASS — Jarvis is untouched, but `LLM_CONTEXT_SIZE` was rewritten during the sweep, so confirm nothing regressed.

- [ ] **Step 11: Mark the spec approved**

In `docs/superpowers/specs/2026-10-04-stress-test-cost-model-design.md`, change `Status: Proposed` to:

```
Status: Implemented
```

- [ ] **Step 12: Commit**

```bash
git add docs/cost-model.md docs/models.md tests/assert-project-shape.ps1 docs/superpowers/specs/2026-10-04-stress-test-cost-model-design.md
git commit -m "docs: measured concurrency sweep and break-even cost model"
```

- [ ] **Step 13: Confirm benchmarks/ stayed out of git**

```bash
git status --short benchmarks/
```

Expected: no output. Raw sweep JSON is gitignored; only the derived tables are committed.

---

## Self-Review Notes

Spec coverage check against `docs/superpowers/specs/2026-10-04-stress-test-cost-model-design.md`:

| Spec requirement | Task |
| --- | --- |
| `--parallel ${LLM_PARALLEL:-1}` in compose, `.env.example` key | 1 |
| Fixed 2048 ctx/slot, sweep 1/2/4/8 | 5 (step 3), 6 (step 6) |
| `ignore_eos` + fixed `max_tokens` | 4 (`load.py` payload) |
| Distinct prompt per client, cache self-check | 4 (`build_prompt`, `prefill_valid`) |
| Target `hpz440:8080`, never localhost | 4 (default), 5 (assertion `Assert-FileNotContains 'localhost:8080'`) |
| TTFT/latency percentiles | 4 (`metrics.percentile`) |
| GPU watts incl. idle baseline, VRAM peak | 5 (`Start-GpuSampler`, `Get-SamplerStats`) |
| `.env` restored in `finally`, incl. Ctrl+C | 5 (step 3 `finally`, step 6 hash check) |
| Break-even model with the exact formula | 2 |
| Mix 1000/300, `h_active` swept over 30/100/300/720 | 2 (constants), 6 (`HOURS_ACTIVE_OPTIONS`) |
| Price provenance enforced, no recalled prices | 3 (`_check_provenance`, `test_shipped_prices_file_is_valid`) |
| Hosted small-open + other local hardware; no frontier | 3 (step 4 instructions) |
| GPU-only watts caveat stated as a lower bound | 6 (step 9), asserted in step 10 |
| Rows into `docs/models.md`, economics into `docs/cost-model.md` | 6 |
| Failure table: oom, unhealthy, request error, Ctrl+C, no telemetry | 5 (step 3 branches) |
| Test assertions updated in the same change | 1, 5, 6 |

Out of scope per the spec and absent here by design: context-length sweep, quantization comparison, vLLM/TGI, frontier price rows, whole-box power.
