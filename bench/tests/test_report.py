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
