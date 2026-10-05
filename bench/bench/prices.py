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
