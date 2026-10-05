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


def test_shipped_prices_file_is_valid():
    """The committed prices.json must itself satisfy the provenance rule."""
    path = Path(prices.__file__).resolve().parent / "prices.json"
    hosted, hardware = prices.load_prices(path)
    assert hosted, "no hosted prices recorded"
    assert hardware, "no hardware prices recorded"
