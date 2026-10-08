"""The inbox is Obi-Wan's only writable location besides /data (H7, decision 8). What is pending is what is still here."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from obiwan.chunking import chunk_text
from obiwan.core.config import RESERVED_ROOT, Settings
from obiwan.core.ids import sha256_file
from obiwan.extract import ExtractionError, extract_text, is_supported, media_type_for
from obiwan.projection import FtsProjection
from obiwan.record import Record

PARTIAL_SUFFIXES = {".tmp", ".part", ".crdownload"}


class InboxReport(BaseModel):
    recorded: int = 0
    failed: int = 0
    items: list[dict] = Field(default_factory=list)


def _unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    n = 1
    while True:
        candidate = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
        if not candidate.exists() and not candidate.with_name(candidate.name + ".error.json").exists():
            return candidate
        n += 1


class Inbox:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.failed_dir = self.path / "failed"
        (self.path / "processed").mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(exist_ok=True)

    def pending(self) -> list[Path]:
        return sorted(p for p in self.path.iterdir()
                      if p.is_file() and not p.name.startswith(".") and p.suffix.lower() not in PARTIAL_SUFFIXES)

    def processed_dir(self, day: date) -> Path:
        d = self.path / "processed" / day.isoformat()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def destination(self, p: Path, day: date) -> Path:
        return _unique(self.processed_dir(day) / p.name)

    def move_failed(self, p: Path, *, error: dict) -> Path:
        dest = _unique(self.failed_dir / p.name)
        dest.with_name(dest.name + ".error.json").write_text(json.dumps(error, indent=2, default=str), encoding="utf-8")
        p.replace(dest)
        return dest


def process_inbox(inbox: Inbox, *, record: Record, projection: FtsProjection, settings: Settings, scan_id: str,
                  now: datetime) -> InboxReport:
    """Extract first, in memory; then record and move inside one transaction, so a failure leaves nothing partial."""
    report = InboxReport()
    for p in inbox.pending():
        try:
            if not is_supported(p):
                raise ExtractionError(f"unsupported file type {p.suffix!r}")
            size = p.stat().st_size
            if size > settings.max_file_bytes:
                raise ExtractionError(f"file is {size} bytes, above the {settings.max_file_bytes} limit")
            digest = sha256_file(p)
            text = extract_text(p, max_pdf_pages=settings.max_pdf_pages)
            specs = chunk_text(text, chunk_chars=settings.chunk_chars)
        except Exception as e:  # noqa: BLE001 - the reason goes beside the file, whatever it was
            error = {"file": p.name, "error": f"{type(e).__name__}: {e}"[:1000], "at": now.isoformat(), "scan_id": scan_id}
            dest = inbox.move_failed(p, error=error)
            record.add_event("inbox_failed", payload={**error, "moved_to": str(dest.relative_to(inbox.path).as_posix())})
            report.failed += 1
            report.items.append({"file": p.name, "outcome": "failed", "error": error["error"]})
            continue
        dest = inbox.destination(p, now.date())
        rel = dest.relative_to(inbox.path).as_posix()
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=now.tzinfo).isoformat()
        with record.transaction():
            duplicate_of = next(iter(record.file_ids_with_hash(digest)), None)
            file_id = record.mint_file(root=RESERVED_ROOT, first_seen_at=now, duplicate_of=duplicate_of)
            record.add_sighting(file_id=file_id, root=RESERVED_ROOT, path=rel, content_hash=digest, size=size, mtime=mtime,
                                seen_at=now, scan_id=scan_id)
            doc = record.add_document(subject_id=file_id, origin="source", content_hash=digest, media_type=media_type_for(p),
                                      size=size, mtime=mtime, title=p.name, scan_id=scan_id, created_at=now)
            chunks = record.add_chunks(doc.doc_id, specs)
            p.replace(dest)  # inside the transaction: if the move fails, the record rolls back and the file stays pending
        projection.index_document(doc, chunks, now=now)
        record.add_event("inbox_recorded", payload={"file": p.name, "doc_id": doc.doc_id, "file_id": file_id, "moved_to": rel,
                                                    "duplicate_of": duplicate_of})
        report.recorded += 1
        report.items.append({"file": p.name, "outcome": "recorded", "doc_id": doc.doc_id, "moved_to": rel})
    return report
