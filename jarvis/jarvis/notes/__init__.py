"""Durable teaching notes: append-only JSONL, latest version per id wins. Pending notes are never injected."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

from jarvis.core.nko import utcnow
from jarvis.journal import Journal, JournalEvent

AppliesTo = Literal["classify", "draft", "chat", "all"]
Status = Literal["pending", "active", "retired"]
Source = Literal["explicit", "proposed"]
MAX_TEXT = 500
RENDER_TRUNCATED = "\n... (older notes omitted)"


class Note(BaseModel):
    id: str
    version: int = 0
    text: str
    applies_to: AppliesTo
    status: Status
    source: Source
    created_at: datetime
    updated_at: datetime
    reason: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _clip(cls, v: object) -> str:
        return str(v or "").strip()[:MAX_TEXT]


class Notes:
    def __init__(self, data_dir: Path, journal: Journal) -> None:
        self.path = Path(data_dir) / "notes" / "notes.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._journal = journal

    def _load(self) -> dict[str, Note]:
        latest: dict[str, Note] = {}
        if not self.path.exists():
            return latest
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                n = Note.model_validate_json(line)
                if n.id not in latest or n.version > latest[n.id].version:
                    latest[n.id] = n
        return latest

    def _append(self, note: Note) -> Note:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(note.model_dump_json() + "\n")
        self._journal.append(JournalEvent.new("note", payload={"note_id": note.id, "version": note.version, "status": note.status,
                                                               "source": note.source, "applies_to": note.applies_to}))
        return note

    def get(self, note_id: str) -> Note | None:
        return self._load().get(note_id)

    def propose(self, text: str, applies_to: AppliesTo, source: Source) -> Note:
        now = utcnow()
        return self._append(Note(id=secrets.token_hex(4), text=text, applies_to=applies_to,
                                 status="active" if source == "explicit" else "pending", source=source,
                                 created_at=now, updated_at=now))

    def _transition(self, note_id: str, allowed_from: tuple[str, ...], status: Status, reason: str | None) -> Note:
        current = self._load().get(note_id)
        if current is None:
            raise KeyError(note_id)
        if current.status not in allowed_from:
            raise ValueError(f"note {note_id} is {current.status}, cannot move to {status}")
        return self._append(current.model_copy(update={"version": current.version + 1, "status": status,
                                                       "reason": reason, "updated_at": utcnow()}))

    def confirm(self, note_id: str) -> Note:
        return self._transition(note_id, ("pending",), "active", None)

    def retire(self, note_id: str, reason: str) -> Note:
        return self._transition(note_id, ("active", "pending"), "retired", reason)

    def retire_all_pending(self, reason: str) -> int:
        """Retire every pending note at once. One stray model turn can leave a dozen proposals behind."""
        retired = 0
        for n in self.all_latest():
            if n.status == "pending":
                self._transition(n.id, ("pending",), "retired", reason)
                retired += 1
        return retired

    def all_latest(self) -> list[Note]:
        return sorted(self._load().values(), key=lambda n: n.created_at)

    def active(self, applies_to: str) -> list[Note]:
        return [n for n in self.all_latest()
                if n.status == "active" and (applies_to == "all" or n.applies_to in (applies_to, "all"))]

    def expire_pending(self, older_than: timedelta = timedelta(days=1), now: datetime | None = None) -> int:
        now = now or utcnow()
        expired = 0
        for n in self.all_latest():
            if n.status == "pending" and now - n.created_at > older_than:
                self._transition(n.id, ("pending",), "retired", "expired")
                expired += 1
        return expired

    def render_for_prompt(self, applies_to: str, max_chars: int = 4000) -> str:
        notes = self.active(applies_to)
        if not notes:
            return ""
        block = "Notes from Conrad:\n" + "\n".join(f"{i}. {n.text}" for i, n in enumerate(notes, 1))
        if len(block) > max_chars:  # an unbounded note set must not crowd the transcript out of the context
            block = block[: max(0, max_chars - len(RENDER_TRUNCATED))] + RENDER_TRUNCATED
        return block
