"""Append-only JSONL event log, one file per UTC day under <data>/journal/."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from jarvis.core.nko import utcnow

EventKind = Literal["run", "capture", "classify", "draft", "correction", "policy_reject", "error", "tool_call", "chat", "note"]


class JournalEvent(BaseModel):
    ts: datetime
    kind: EventKind
    nko_id: UUID | None = None
    dedup_key: str | None = None
    version: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def new(cls, kind: EventKind, *, nko_id: UUID | None = None, dedup_key: str | None = None,
            version: int | None = None, payload: dict[str, Any] | None = None) -> JournalEvent:
        return cls(ts=utcnow(), kind=kind, nko_id=nko_id, dedup_key=dedup_key, version=version, payload=payload or {})


class Journal:
    def __init__(self, data_dir: Path) -> None:
        self.dir = Path(data_dir) / "journal"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.skipped_lines = 0

    def _file(self, day: date) -> Path:
        return self.dir / f"{day.isoformat()}.jsonl"

    def append(self, event: JournalEvent) -> None:
        with self._file(event.ts.date()).open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def _parse(self, path: Path) -> list[JournalEvent]:
        out: list[JournalEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(JournalEvent.model_validate_json(line))
            except ValidationError:
                self.skipped_lines += 1
        return out

    def read(self, day: date) -> list[JournalEvent]:
        p = self._file(day)
        return self._parse(p) if p.exists() else []

    def _files(self) -> list[Path]:
        return sorted(self.dir.glob("*.jsonl"))

    def iter_all(self) -> Iterator[JournalEvent]:
        for p in self._files():
            yield from self._parse(p)

    def events_for(self, dedup_key: str) -> list[JournalEvent]:
        return [e for e in self.iter_all() if e.dedup_key == dedup_key]

    def error_count_for(self, dedup_key: str) -> int:
        return sum(1 for e in self.iter_all() if e.kind == "error" and e.dedup_key == dedup_key)

    def last_run(self) -> JournalEvent | None:
        return self._last(lambda e: e.kind == "run")

    def last_error_for(self, dedup_key: str) -> JournalEvent | None:
        return self._last(lambda e: e.kind == "error" and e.dedup_key == dedup_key)

    def _last(self, pred: Callable[[JournalEvent], bool]) -> JournalEvent | None:
        for p in reversed(self._files()):
            hits = [e for e in self._parse(p) if pred(e)]
            if hits:
                return hits[-1]
        return None
