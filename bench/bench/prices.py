"""Price data with mandatory provenance.

Every number in the comparison must be traceable to a URL and a date it was
fetched. This loader rejects a record that is missing either, so a price
recalled from memory cannot reach the writeup.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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
    source_url: str
    retrieved: str
    measured_here: bool


def _check_provenance(record: dict, label: str) -> None:
    if not record.get("source_url"):
        raise ValueError(f"{label}: missing source_url. Fetch the price, do not recall it.")
    retrieved = record.get("retrieved", "")
    if not _DATE.match(str(retrieved)):
        raise ValueError(f"{label}: retrieved must be YYYY-MM-DD, got {retrieved!r}")


def load_prices(path: Path | str) -> tuple[list[HostedPrice], list[HardwarePrice]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    hosted: list[HostedPrice] = []
    for record in payload.get("hosted", []):
        label = f"{record.get('provider', '?')}/{record.get('model', '?')}"
        _check_provenance(record, label)
        hosted.append(
            HostedPrice(
                provider=record["provider"],
                model=record["model"],
                usd_per_mtok_in=float(record["usd_per_mtok_in"]),
                usd_per_mtok_out=float(record["usd_per_mtok_out"]),
                source_url=record["source_url"],
                retrieved=record["retrieved"],
            )
        )

    hardware: list[HardwarePrice] = []
    for record in payload.get("hardware", []):
        label = record.get("name", "?")
        _check_provenance(record, label)
        decode = record.get("decode_tps_7b_q4")
        hardware.append(
            HardwarePrice(
                name=record["name"],
                usd=float(record["usd"]),
                decode_tps_7b_q4=None if decode is None else float(decode),
                source_url=record["source_url"],
                retrieved=record["retrieved"],
                measured_here=bool(record.get("measured_here", False)),
            )
        )

    return hosted, hardware
