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
    # 1000 prompt tokens in 1000 ms = 1000 tok/s, per request; 4 requests is the same rate.
    samples = [_sample() for _ in range(4)]
    out = summarize(samples, wall_seconds=10.0, slots=2, ctx_per_slot=2048)
    assert out["prefill_tps"] == pytest.approx(1000.0)


def test_summarize_flags_cache_contamination():
    clean = [_sample(cached_tokens=5) for _ in range(4)]  # 20 of 4000 = 0.5%
    assert summarize(clean, wall_seconds=10.0, slots=2, ctx_per_slot=2048)["prefill_valid"] is True

    dirty = [_sample(cached_tokens=500) for _ in range(4)]  # 2000 of 4000 = 50%
    out = summarize(dirty, wall_seconds=10.0, slots=2, ctx_per_slot=2048)
    assert out["prefill_valid"] is False
    assert out["cached_tokens_total"] == 2000


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
