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
