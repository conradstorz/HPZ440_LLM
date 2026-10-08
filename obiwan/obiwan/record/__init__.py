"""The record. This class is the only code that writes record tables (S3); everything else reads through it."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from obiwan.chunking import ChunkSpec
from obiwan.core.ids import new_id, utcnow
from obiwan.record.schema import APPEND_ONLY, ATTESTATIONS, ORIGINS, POWERS, SCHEMA, SCHEMA_VERSION, TRIGGERS

__all__ = ["APPEND_ONLY", "ATTESTATIONS", "ORIGINS", "POWERS", "Chunk", "Document", "Event", "FileRow", "Record",
           "Sighting", "Tombstone"]


class FileRow(BaseModel):
    file_id: str
    root: str
    first_seen_at: datetime
    duplicate_of: str | None = None


class Sighting(BaseModel):
    id: int
    file_id: str
    root: str
    path: str
    content_hash: str
    size: int
    mtime: str
    seen_at: datetime
    scan_id: str


class Document(BaseModel):
    doc_id: str
    subject_id: str
    version_no: int
    origin: str
    attestation: str | None = None
    content_hash: str
    size: int | None = None
    mtime: str | None = None
    media_type: str
    title: str | None = None
    submitted_by: str | None = None
    conversation_ref: str | None = None
    promotion_of: str | None = None
    scan_id: str | None = None
    created_at: datetime


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    seq: int
    start_char: int
    end_char: int
    text: str


class Tombstone(BaseModel):
    id: int
    subject_id: str
    reason: str
    ordered_by: str
    created_at: datetime


class Event(BaseModel):
    id: int
    ts: datetime
    kind: str
    role: str | None = None
    payload: dict[str, Any]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class Record:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode: single statements commit at once; multi-statement work uses transaction().
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA + TRIGGERS)
        now = _iso(utcnow())
        for role, powers in POWERS.items():
            for power in sorted(powers):
                self.conn.execute("INSERT OR IGNORE INTO powers(role, power, granted_at) VALUES (?, ?, ?)", (role, power, now))
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._lock = threading.RLock()
        self._depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """All-or-nothing across several writes. Nested calls join the outermost transaction."""
        with self._lock:
            if self._depth == 0:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    # ----- writes -----

    def mint_file(self, *, root: str, first_seen_at: datetime, duplicate_of: str | None = None) -> str:
        file_id = new_id()
        self.conn.execute("INSERT INTO files(file_id, root, first_seen_at, duplicate_of) VALUES (?, ?, ?, ?)",
                          (file_id, root, _iso(first_seen_at), duplicate_of))
        return file_id

    def add_sighting(self, *, file_id: str, root: str, path: str, content_hash: str, size: int, mtime: str,
                     seen_at: datetime, scan_id: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO sightings(file_id, root, path, content_hash, size, mtime, seen_at, scan_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, root, path, content_hash, size, mtime, _iso(seen_at), scan_id))
        return int(cur.lastrowid)

    def add_document(self, *, subject_id: str, origin: str, content_hash: str, media_type: str, created_at: datetime,
                     attestation: str | None = None, size: int | None = None, mtime: str | None = None,
                     title: str | None = None, submitted_by: str | None = None, conversation_ref: str | None = None,
                     promotion_of: str | None = None, scan_id: str | None = None) -> Document:
        with self.transaction():
            row = self.conn.execute("SELECT coalesce(max(version_no), 0) FROM documents WHERE subject_id = ?", (subject_id,)).fetchone()
            doc_id = new_id()
            self.conn.execute(
                "INSERT INTO documents(doc_id, subject_id, version_no, origin, attestation, content_hash, size, mtime, media_type, "
                "title, submitted_by, conversation_ref, promotion_of, scan_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, subject_id, row[0] + 1, origin, attestation, content_hash, size, mtime, media_type, title,
                 submitted_by, conversation_ref, promotion_of, scan_id, _iso(created_at)))
        return self.document(doc_id)

    def add_text(self, doc_id: str, content: str) -> None:
        self.conn.execute("INSERT INTO texts(doc_id, content) VALUES (?, ?)", (doc_id, content))

    def add_chunks(self, doc_id: str, specs: Iterable[ChunkSpec]) -> list[Chunk]:
        out = []
        with self.transaction():
            for s in specs:
                chunk_id = f"{doc_id}-{s.seq}"
                self.conn.execute("INSERT INTO chunks(chunk_id, doc_id, seq, start_char, end_char, text) VALUES (?, ?, ?, ?, ?, ?)",
                                  (chunk_id, doc_id, s.seq, s.start_char, s.end_char, s.text))
                out.append(Chunk(chunk_id=chunk_id, doc_id=doc_id, seq=s.seq, start_char=s.start_char, end_char=s.end_char, text=s.text))
        return out

    def add_tombstone(self, *, subject_id: str, reason: str, ordered_by: str, created_at: datetime) -> Tombstone:
        cur = self.conn.execute("INSERT INTO tombstones(subject_id, reason, ordered_by, created_at) VALUES (?, ?, ?, ?)",
                                (subject_id, reason, ordered_by, _iso(created_at)))
        return Tombstone(id=int(cur.lastrowid), subject_id=subject_id, reason=reason, ordered_by=ordered_by, created_at=created_at)

    def add_event(self, kind: str, *, role: str | None = None, payload: dict[str, Any] | None = None) -> None:
        self.conn.execute("INSERT INTO events(ts, kind, role, payload) VALUES (?, ?, ?, ?)",
                          (_iso(utcnow()), kind, role, json.dumps(payload or {}, ensure_ascii=False, default=str)))

    def add_scan(self, *, scan_id: str, started_at: datetime, finished_at: datetime, report: dict[str, Any]) -> None:
        self.conn.execute("INSERT INTO scans(scan_id, started_at, finished_at, report) VALUES (?, ?, ?, ?)",
                          (scan_id, _iso(started_at), _iso(finished_at), json.dumps(report, ensure_ascii=False, default=str)))

    # ----- reads -----

    def _one(self, model, sql: str, params: tuple = ()):
        row = self.conn.execute(sql, params).fetchone()
        return model.model_validate(dict(row)) if row else None

    def _many(self, model, sql: str, params: tuple = ()) -> list:
        return [model.model_validate(dict(r)) for r in self.conn.execute(sql, params).fetchall()]

    def latest_sighting_at(self, root: str, path: str) -> Sighting | None:
        return self._one(Sighting, "SELECT * FROM sightings WHERE root = ? AND path = ? ORDER BY id DESC LIMIT 1", (root, path))

    def latest_sighting(self, file_id: str) -> Sighting | None:
        return self._one(Sighting, "SELECT * FROM sightings WHERE file_id = ? ORDER BY id DESC LIMIT 1", (file_id,))

    def sightings_for(self, file_id: str) -> list[Sighting]:
        return self._many(Sighting, "SELECT * FROM sightings WHERE file_id = ? ORDER BY id", (file_id,))

    def file_ids_with_hash(self, content_hash: str) -> list[str]:
        """Files whose LATEST sighting carries this hash, oldest file first."""
        rows = self.conn.execute(
            "SELECT s.file_id FROM sightings s WHERE s.id = (SELECT max(id) FROM sightings WHERE file_id = s.file_id) "
            "AND s.content_hash = ? ORDER BY s.id", (content_hash,)).fetchall()
        return [r[0] for r in rows]

    def file(self, file_id: str) -> FileRow | None:
        return self._one(FileRow, "SELECT * FROM files WHERE file_id = ?", (file_id,))

    def document(self, doc_id: str) -> Document | None:
        return self._one(Document, "SELECT * FROM documents WHERE doc_id = ?", (doc_id,))

    def latest_document(self, subject_id: str) -> Document | None:
        return self._one(Document, "SELECT * FROM documents WHERE subject_id = ? ORDER BY version_no DESC LIMIT 1", (subject_id,))

    def documents_for(self, subject_id: str) -> list[Document]:
        return self._many(Document, "SELECT * FROM documents WHERE subject_id = ? ORDER BY version_no", (subject_id,))

    def latest_documents(self) -> list[Document]:
        return self._many(Document, "SELECT d.* FROM documents d WHERE d.version_no = "
                                    "(SELECT max(version_no) FROM documents WHERE subject_id = d.subject_id) ORDER BY d.created_at, d.doc_id")

    def text(self, doc_id: str) -> str | None:
        row = self.conn.execute("SELECT content FROM texts WHERE doc_id = ?", (doc_id,)).fetchone()
        return row[0] if row else None

    def chunk(self, chunk_id: str) -> Chunk | None:
        return self._one(Chunk, "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,))

    def chunks_for(self, doc_id: str) -> list[Chunk]:
        return self._many(Chunk, "SELECT * FROM chunks WHERE doc_id = ? ORDER BY seq", (doc_id,))

    def chunk_ids_for_subject(self, subject_id: str) -> list[str]:
        rows = self.conn.execute("SELECT c.chunk_id FROM chunks c JOIN documents d ON d.doc_id = c.doc_id WHERE d.subject_id = ? "
                                 "ORDER BY d.version_no, c.seq", (subject_id,)).fetchall()
        return [r[0] for r in rows]

    def tombstone_for(self, subject_id: str) -> Tombstone | None:
        return self._one(Tombstone, "SELECT * FROM tombstones WHERE subject_id = ? ORDER BY id DESC LIMIT 1", (subject_id,))

    def powers_for(self, role: str) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT power FROM powers WHERE role = ?", (role,)).fetchall()}

    def events(self, *, limit: int = 50, kind: str | None = None) -> list[Event]:
        sql = "SELECT id, ts, kind, role, payload FROM events" + (" WHERE kind = ?" if kind else "") + " ORDER BY id DESC LIMIT ?"
        params: tuple = (kind, limit) if kind else (limit,)
        return [Event(id=r["id"], ts=r["ts"], kind=r["kind"], role=r["role"], payload=json.loads(r["payload"]))
                for r in self.conn.execute(sql, params).fetchall()]

    def last_scan(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM scans ORDER BY finished_at DESC, rowid DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {"scan_id": row["scan_id"], "started_at": row["started_at"], "finished_at": row["finished_at"], "report": json.loads(row["report"])}

    _LATEST_LIVE = ("WITH latest AS (SELECT d.* FROM documents d WHERE d.version_no = "
                    "(SELECT max(version_no) FROM documents WHERE subject_id = d.subject_id) "
                    "AND d.subject_id NOT IN (SELECT subject_id FROM tombstones)) ")

    def coverage_counts(self) -> dict[str, int]:
        """S10: how much of the latest, non-forgotten record is searchable right now."""
        q = self.conn.execute
        documents = q(self._LATEST_LIVE + "SELECT count(*) FROM latest").fetchone()[0]
        chunks = q(self._LATEST_LIVE + "SELECT count(*) FROM chunks c JOIN latest l ON l.doc_id = c.doc_id").fetchone()[0]
        chunks_indexed = q(self._LATEST_LIVE + "SELECT count(*) FROM chunks c JOIN latest l ON l.doc_id = c.doc_id "
                           "JOIN projection p ON p.chunk_id = c.chunk_id AND p.kind = 'fts' AND p.state = 'current'").fetchone()[0]
        documents_indexed = q(self._LATEST_LIVE + "SELECT count(*) FROM latest l WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.doc_id = l.doc_id) "
                              "AND NOT EXISTS (SELECT 1 FROM chunks c LEFT JOIN projection p ON p.chunk_id = c.chunk_id AND p.kind = 'fts' "
                              "WHERE c.doc_id = l.doc_id AND (p.state IS NULL OR p.state != 'current'))").fetchone()[0]
        tombstoned = q("SELECT count(DISTINCT subject_id) FROM tombstones").fetchone()[0]
        return {"documents": documents, "documents_indexed": documents_indexed, "chunks": chunks, "chunks_indexed": chunks_indexed,
                "tombstoned": tombstoned}
