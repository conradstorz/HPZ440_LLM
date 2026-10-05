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
            "source_url": "https://example.invalid/bench",
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


def test_rejects_hosted_entry_without_source(tmp_path):
    payload = json.loads(json.dumps(GOOD))
    del payload["hosted"][0]["source_url"]
    with pytest.raises(ValueError, match="Llama-3.1-8B-Instruct"):
        prices.load_prices(_write(tmp_path, payload))


def test_rejects_hardware_entry_without_source(tmp_path):
    payload = json.loads(json.dumps(GOOD))
    payload["hardware"][0]["source_url"] = ""
    with pytest.raises(ValueError, match="RTX 3060"):
        prices.load_prices(_write(tmp_path, payload))


def test_rejects_malformed_retrieved_date(tmp_path):
    payload = json.loads(json.dumps(GOOD))
    payload["hosted"][0]["retrieved"] = "Oct 2026"
    with pytest.raises(ValueError, match="retrieved"):
        prices.load_prices(_write(tmp_path, payload))


def test_shipped_prices_file_is_valid():
    """The committed prices.json must itself satisfy the provenance rule."""
    path = Path(prices.__file__).resolve().parent / "prices.json"
    hosted, hardware = prices.load_prices(path)
    assert hosted, "no hosted prices recorded"
    assert hardware, "no hardware prices recorded"
