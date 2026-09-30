"""SQLite FTS5 index over archived mail. Disposable: rebuild() recreates it from the Store."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from jarvis.core.nko import NKO, Evidence, sender_address
from jarvis.core.store import Store

SCHEMA_VERSION = 1
_WORD = re.compile(r"\w+")


class Index:
    def __init__(self, data_dir: Path, store: Store) -> None:
        self._store = store
        self.path = Path(data_dir) / "index" / "mail.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The web app builds Index on the main thread and calls it from request worker threads. Safe because
        # /run is serialised by web.py's run_lock and no other route touches the index.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        if self._conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            self.rebuild()

    def _create(self) -> None:
        self._conn.executescript(
            "DROP TABLE IF EXISTS docs;"
            "CREATE VIRTUAL TABLE docs USING fts5(dedup_key UNINDEXED, nko_id UNINDEXED, received_at UNINDEXED, sender, subject, content);"
            f"PRAGMA user_version = {SCHEMA_VERSION};"
        )
        self._conn.commit()

    def index(self, nko: NKO) -> None:
        self._conn.execute("DELETE FROM docs WHERE dedup_key = ?", (nko.dedup_key,))
        self._conn.execute(
            "INSERT INTO docs (dedup_key, nko_id, received_at, sender, subject, content) VALUES (?, ?, ?, ?, ?, ?)",
            (nko.dedup_key, str(nko.id), nko.received_at.isoformat(), sender_address(nko), nko.subject or "", nko.content or ""),
        )
        self._conn.commit()

    def search(self, query: str, k: int = 5, exclude: str | None = None) -> list[Evidence]:
        terms = [t for t in _WORD.findall(query) if len(t) > 1]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self._conn.execute(
            "SELECT dedup_key, nko_id, received_at, subject, snippet(docs, 5, '', '', '...', 20), bm25(docs) "
            "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
            (match, k + 1),
        ).fetchall()
        out = []
        for dedup_key, nko_id, received_at, subject, snippet, score in rows:
            if dedup_key == exclude:
                continue
            out.append(Evidence(nko_id=nko_id, dedup_key=dedup_key, subject=subject,
                                received_at=datetime.fromisoformat(received_at), snippet=snippet, score=-float(score)))
        return out[:k]

    def rebuild(self) -> int:
        self._create()
        n = 0
        for nko in self._store.iter_latest():
            self.index(nko)
            n += 1
        return n

    def count(self) -> int:
        return self._conn.execute("SELECT count(*) FROM docs").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
