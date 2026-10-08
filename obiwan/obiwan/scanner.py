"""Discovery and identity (mvp.md sections 4 and 12). The path is an attribute; file_id is identity; a new hash for a
known file_id is a new version. Source roots are only ever read."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from obiwan.core.ids import sha256_file
from obiwan.extract import is_supported, media_type_for
from obiwan.record import Record
from obiwan.work import WorkQueue


class RootReport(BaseModel):
    name: str
    path: str
    reachable: bool = False
    error: str | None = None
    seen: int = 0
    new: int = 0
    unchanged: int = 0
    changed: int = 0
    moved: int = 0
    duplicates: int = 0
    skipped_unsupported: int = 0
    skipped_large: int = 0
    errors: list[str] = Field(default_factory=list)


def discover(root_path: Path, *, max_file_bytes: int) -> tuple[list[Path], int, int]:
    """Supported, size-bounded regular files under the root, sorted for determinism. Raises OSError if the root cannot be listed."""
    paths, unsupported, large = [], 0, 0
    for p in sorted(x for x in root_path.rglob("*") if x.is_file()):
        if not is_supported(p):
            unsupported += 1
        elif p.stat().st_size > max_file_bytes:
            large += 1
        else:
            paths.append(p)
    return paths, unsupported, large


def _resolve(record: Record, work: WorkQueue, *, name: str, rel: str, digest: str, size: int, mtime: str, media_type: str,
             on_disk: set[str], scan_id: str, now: datetime) -> str:
    """Classify one discovered file against the record and write what follows. Returns the RootReport counter to bump."""
    sighting = dict(root=name, path=rel, content_hash=digest, size=size, mtime=mtime, seen_at=now, scan_id=scan_id)
    known = record.latest_sighting_at(name, rel)
    if known is not None:
        record.add_sighting(file_id=known.file_id, **sighting)
        if known.content_hash == digest:
            return "unchanged"
        doc = record.add_document(subject_id=known.file_id, origin="source", content_hash=digest, media_type=media_type,
                                  size=size, mtime=mtime, title=rel, scan_id=scan_id, created_at=now)
        work.enqueue("extract", doc.doc_id, now=now)
        return "changed"
    # Unknown path. The documented move rule: same bytes, old path in this root gone from disk -> the same file, moved.
    same_hash = record.file_ids_with_hash(digest)
    movers = []
    for fid in same_hash:
        last = record.latest_sighting(fid)
        if last is not None and last.root == name and last.path not in on_disk:
            movers.append(fid)
    if len(movers) == 1:
        record.add_sighting(file_id=movers[0], **sighting)
        return "moved"
    # Two files with identical content at two paths are two files, with the duplication noted rather than resolved.
    duplicate_of = same_hash[0] if same_hash else None
    file_id = record.mint_file(root=name, first_seen_at=now, duplicate_of=duplicate_of)
    record.add_sighting(file_id=file_id, **sighting)
    doc = record.add_document(subject_id=file_id, origin="source", content_hash=digest, media_type=media_type,
                              size=size, mtime=mtime, title=rel, scan_id=scan_id, created_at=now)
    work.enqueue("extract", doc.doc_id, now=now)
    return "duplicates" if duplicate_of else "new"


def scan_root(name: str, root_path: Path, *, record: Record, work: WorkQueue, scan_id: str, now: datetime,
              max_file_bytes: int) -> RootReport:
    report = RootReport(name=name, path=str(root_path))
    root_path = Path(root_path)
    if not root_path.is_dir():
        report.error = "root not reachable"
        return report  # S11: a gap, reported. Nothing is marked deleted because a mount was absent.
    try:
        paths, report.skipped_unsupported, report.skipped_large = discover(root_path, max_file_bytes=max_file_bytes)
    except OSError as e:
        report.error = f"{type(e).__name__}: {e}"
        return report
    report.reachable = True
    on_disk = {p.relative_to(root_path).as_posix() for p in paths}
    for p in paths:
        rel = p.relative_to(root_path).as_posix()
        try:
            st = p.stat()
            digest = sha256_file(p)
        except OSError as e:  # vanished mid-scan: skip it this time, the record is untouched
            report.errors.append(f"{rel}: {type(e).__name__}")
            continue
        mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat()
        with record.transaction():
            outcome = _resolve(record, work, name=name, rel=rel, digest=digest, size=st.st_size, mtime=mtime,
                               media_type=media_type_for(p), on_disk=on_disk, scan_id=scan_id, now=now)
        report.seen += 1
        setattr(report, outcome, getattr(report, outcome) + 1)
    return report


def scan_roots(roots: dict[str, Path], *, record: Record, work: WorkQueue, scan_id: str, now: datetime,
               max_file_bytes: int) -> list[RootReport]:
    return [scan_root(name, path, record=record, work=work, scan_id=scan_id, now=now, max_file_bytes=max_file_bytes)
            for name, path in roots.items()]
