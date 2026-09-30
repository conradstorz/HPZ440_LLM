from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Protocol

from jarvis.core.nko import NKO


class Source(Protocol):
    name: str

    def poll(self, since: datetime) -> Iterator[NKO]:
        """Yield v0 NKOs received after ``since``. Must skip dedup_keys already in the store."""
        ...


class FakeSource:
    name = "fake"

    def __init__(self, nkos: Iterable[NKO]) -> None:
        self._nkos = list(nkos)

    def poll(self, since: datetime) -> Iterator[NKO]:
        # Honours ``since`` like a real source so watermark behaviour is testable.
        yield from (n for n in self._nkos if n.received_at >= since)
