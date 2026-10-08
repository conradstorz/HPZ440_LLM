"""The search index is a disposable projection (mvp.md section 9). State lives in the record's projection table, the
searchable payload lives in its own SQLite FTS5 file, which can be deleted and rebuilt from stored chunks at any time."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from obiwan.record import Chunk, Document, Record

KIND = "fts"
SCHEMA_VERSION = 1
_WORD = re.compile(r"\w+")


class Hit(BaseModel):
    chunk_id: str
    score: float
    snippet: str


class FtsProjection:
    def __init__(self, index_dir: Path, record: Record) -> None:
        self._record = record
        self.path = Path(index_dir) / "fts.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._open()

    def _open(self) -> None:
        try:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            stale = self._conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
        except sqlite3.DatabaseError:
            # Disposable: a corrupt or truncated file is discarded rather than blocking startup.
            conn = getattr(self, "_conn", None)
            if conn is not None:
                conn.close()
            self.path.unlink(missing_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            stale = True
        if stale:
            self._create()

    def _create(self) -> None:
        self._conn.executescript(
            "DROP TABLE IF EXISTS chunks_fts;"
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text);"
            f"PRAGMA user_version = {SCHEMA_VERSION};"
        )
        self._conn.commit()

    def _set_state(self, chunk_ids: list[str], state: str, *, reason: str | None, now: datetime) -> None:
        built = now.isoformat() if state == "current" else None
        self._record.conn.executemany(
            "INSERT INTO projection(chunk_id, kind, state, reason, built_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chunk_id, kind) DO UPDATE SET state = excluded.state, reason = excluded.reason, built_at = excluded.built_at",
            [(cid, KIND, state, reason, built) for cid in chunk_ids])

    def _remove(self, chunk_ids: list[str]) -> None:
        self._conn.executemany("DELETE FROM chunks_fts WHERE chunk_id = ?", [(cid,) for cid in chunk_ids])

    def index_document(self, doc: Document, chunks: list[Chunk], *, now: datetime) -> None:
        """Make this version searchable and retire every earlier version of the same subject (decision 6)."""
        ids = [c.chunk_id for c in chunks]
        self._remove(ids)
        self._conn.executemany("INSERT INTO chunks_fts(chunk_id, text) VALUES (?, ?)", [(c.chunk_id, c.text) for c in chunks])
        self._conn.commit()
        self._set_state(ids, "current", reason=None, now=now)
        older = [cid for cid in self._record.chunk_ids_for_subject(doc.subject_id) if cid not in set(ids)
                 and self._record.chunk(cid).doc_id != doc.doc_id]
        if older:
            self._remove(older)
            self._conn.commit()
            self._set_state(older, "stale", reason="superseded", now=now)

    def retire_subject(self, subject_id: str, *, reason: str, now: datetime) -> None:
        ids = self._record.chunk_ids_for_subject(subject_id)
        if ids:
            self._remove(ids)
            self._conn.commit()
            self._set_state(ids, "stale", reason=reason, now=now)

    def search(self, query: str, k: int) -> list[Hit]:
        terms = [t for t in _WORD.findall(query) if len(t) > 1]
        if not terms or k < 1:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self._conn.execute(
            "SELECT chunk_id, bm25(chunks_fts), snippet(chunks_fts, 1, '', '', '...', 24) FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?", (match, k)).fetchall()
        return [Hit(chunk_id=cid, score=-float(score), snippet=snip) for cid, score, snip in rows]

    def rebuild(self, *, now: datetime) -> int:
        """Discard the projection and rebuild it from stored chunks. No source file is read, no text re-extracted."""
        self._create()
        self._record.conn.execute("UPDATE projection SET state = 'pending', reason = NULL, built_at = NULL WHERE kind = ?", (KIND,))
        n = 0
        for doc in self._record.latest_documents():
            if self._record.tombstone_for(doc.subject_id) is not None:
                continue
            chunks = self._record.chunks_for(doc.doc_id)
            if chunks:
                self.index_document(doc, chunks, now=now)
                n += len(chunks)
        # Whatever is still pending belongs to superseded versions or forgotten subjects.
        self._record.conn.execute(
            "UPDATE projection SET state = 'stale', reason = CASE WHEN EXISTS (SELECT 1 FROM chunks c JOIN documents d ON d.doc_id = c.doc_id "
            "JOIN tombstones t ON t.subject_id = d.subject_id WHERE c.chunk_id = projection.chunk_id) THEN 'forgotten' ELSE 'superseded' END "
            "WHERE kind = ? AND state = 'pending'", (KIND,))
        return n

    def count(self) -> int:
        return self._conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]

    def state_counts(self) -> dict[str, int]:
        rows = self._record.conn.execute("SELECT state, count(*) FROM projection WHERE kind = ? GROUP BY state", (KIND,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def close(self) -> None:
        self._conn.close()
