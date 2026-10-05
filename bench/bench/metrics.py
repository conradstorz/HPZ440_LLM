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
    prefill_tps = (prompt_total / (prompt_ms_total / 1000.0)) if prompt_ms_total > 0 else None
    contaminated = prompt_total > 0 and (cached_total / prompt_total) > CACHE_CONTAMINATION_LIMIT

    return {
        "slots": slots,
        "ctx_per_slot": ctx_per_slot,
        "requests": len(samples),
        "wall_seconds": wall_seconds,
        "output_tokens_total": output_total,
        "prompt_tokens_total": prompt_total,
        "aggregate_output_tps": aggregate_tps,
        "per_client_output_tps": aggregate_tps / slots,
        "prefill_tps": prefill_tps,
        "cached_tokens_total": cached_total,
        "prefill_valid": not contaminated,
        "ttft_ms_p50": percentile([s.ttft_ms for s in samples], 50),
        "ttft_ms_p95": percentile([s.ttft_ms for s in samples], 95),
        "latency_ms_p50": percentile([s.latency_ms for s in samples], 50),
        "latency_ms_p95": percentile([s.latency_ms for s in samples], 95),
    }
