"""S11: deferred work is durable. A row per unit of work, with attempts, last error, next attempt, and a lease."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel

from obiwan.record import Record

MAX_BACKOFF = timedelta(hours=24)


class WorkItem(BaseModel):
    id: int
    kind: str
    target: str
    state: str
    attempts: int
    last_error: str | None = None
    next_attempt_at: datetime
    lease_until: datetime | None = None


def backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** attempts), MAX_BACKOFF)


class WorkQueue:
    def __init__(self, record: Record) -> None:
        self._conn = record.conn

    def enqueue(self, kind: str, target: str, *, now: datetime) -> bool:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO work(kind, target, state, attempts, next_attempt_at, created_at, updated_at) "
            "VALUES (?, ?, 'pending', 0, ?, ?, ?)", (kind, target, now.isoformat(), now.isoformat(), now.isoformat()))
        return cur.rowcount == 1

    _CLAIMABLE = "((state = 'pending' AND next_attempt_at <= :now) OR (state = 'leased' AND lease_until <= :now))"

    def claim(self, *, now: datetime, lease_seconds: int) -> WorkItem | None:
        """Lease the next due item. An expired lease is reclaimed: work stranded by a crash is never lost."""
        params = {"now": now.isoformat(), "until": (now + timedelta(seconds=lease_seconds)).isoformat()}
        row = self._conn.execute(f"SELECT id FROM work WHERE {self._CLAIMABLE} ORDER BY next_attempt_at, id LIMIT 1", params).fetchone()
        if row is None:
            return None
        cur = self._conn.execute(f"UPDATE work SET state = 'leased', lease_until = :until, updated_at = :now "
                                 f"WHERE id = :id AND {self._CLAIMABLE}", {**params, "id": row[0]})
        if cur.rowcount != 1:
            return None  # another claimant won the race; the caller simply tries again later
        return self._item(row[0])

    def complete(self, item_id: int, *, now: datetime) -> None:
        self._conn.execute("UPDATE work SET state = 'done', lease_until = NULL, updated_at = ? WHERE id = ?", (now.isoformat(), item_id))

    def fail(self, item_id: int, error: str, *, now: datetime, max_attempts: int) -> bool:
        item = self._item(item_id)
        attempts = item.attempts + 1
        final = attempts >= max_attempts
        self._conn.execute(
            "UPDATE work SET state = ?, attempts = ?, last_error = ?, next_attempt_at = ?, lease_until = NULL, updated_at = ? WHERE id = ?",
            ("failed" if final else "pending", attempts, error[:1000], (now + backoff(attempts)).isoformat(), now.isoformat(), item_id))
        return final

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT state, count(*) FROM work GROUP BY state").fetchall()
        by = {r[0]: r[1] for r in rows}
        return {"pending": by.get("pending", 0) + by.get("leased", 0), "failed": by.get("failed", 0), "done": by.get("done", 0)}

    def failed(self, *, limit: int = 50) -> list[WorkItem]:
        rows = self._conn.execute("SELECT * FROM work WHERE state = 'failed' ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [WorkItem.model_validate(dict(r)) for r in rows]

    def _item(self, item_id: int) -> WorkItem:
        row = self._conn.execute("SELECT * FROM work WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"no work item {item_id}")
        return WorkItem.model_validate(dict(row))
