"""Drain the work queue: extract, chunk, index. Failures postpone durably (S11); chunks are never deleted by a later failure."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from obiwan.chunking import chunk_text
from obiwan.core.config import Settings
from obiwan.core.ids import sha256_file
from obiwan.extract import extract_text
from obiwan.projection import FtsProjection
from obiwan.record import Record
from obiwan.work import WorkItem, WorkQueue


class RootUnavailable(Exception):
    pass


class ContentChanged(Exception):
    pass


class WorkReport(BaseModel):
    completed: int = 0
    failed: int = 0
    postponed: int = 0
    errors: list[str] = Field(default_factory=list)


def process_item(item: WorkItem, *, record: Record, projection: FtsProjection, roots: dict[str, Path], settings: Settings,
                 now: datetime) -> None:
    if item.kind != "extract":
        raise RuntimeError(f"unknown work kind {item.kind!r}")
    doc = record.document(item.target)
    if doc is None:
        raise RuntimeError(f"document {item.target} is not in the record")
    chunks = record.chunks_for(doc.doc_id)
    if not chunks:  # a reclaimed item may have died between add_chunks and complete(); never write them twice
        sighting = record.latest_sighting(doc.subject_id)
        if sighting is None:
            raise RuntimeError(f"no sighting for subject {doc.subject_id}")
        root_path = roots.get(sighting.root)
        if root_path is None or not Path(root_path).is_dir():
            raise RootUnavailable(f"root {sighting.root!r} is not reachable")
        path = Path(root_path) / sighting.path
        if not path.is_file():
            raise RootUnavailable(f"{sighting.root}:{sighting.path} is not present; a later scan will relocate it")
        if sha256_file(path) != doc.content_hash:
            raise ContentChanged(f"{sighting.root}:{sighting.path} changed since scan {doc.scan_id}; the next scan records a new version")
        text = extract_text(path, max_pdf_pages=settings.max_pdf_pages)
        chunks = record.add_chunks(doc.doc_id, chunk_text(text, chunk_chars=settings.chunk_chars))
    projection.index_document(doc, chunks, now=now)


def drain(*, record: Record, work: WorkQueue, projection: FtsProjection, roots: dict[str, Path], settings: Settings,
          now: datetime, limit: int = 10_000) -> WorkReport:
    """Claim and process every item due at ``now``. An item that fails gets a future next_attempt_at, so it is not
    re-claimed within this drain: there is no tight loop by construction."""
    report = WorkReport()
    for _ in range(limit):
        item = work.claim(now=now, lease_seconds=settings.lease_seconds)
        if item is None:
            break
        try:
            process_item(item, record=record, projection=projection, roots=roots, settings=settings, now=now)
        except Exception as e:  # noqa: BLE001 - every failure becomes a durable row with its reason
            message = f"{type(e).__name__}: {e}"[:500]
            final = work.fail(item.id, message, now=now, max_attempts=settings.max_attempts)
            record.add_event("work_failed", payload={"work_id": item.id, "kind": item.kind, "target": item.target,
                                                     "attempt": item.attempts + 1, "final": final, "error": message})
            report.errors.append(message)
            if final:
                report.failed += 1
            else:
                report.postponed += 1
            continue
        work.complete(item.id, now=now)
        report.completed += 1
    return report
