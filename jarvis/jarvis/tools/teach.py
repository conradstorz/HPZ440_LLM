"""Teaching tools: list, propose, confirm, retire notes."""

from __future__ import annotations

from jarvis.notes import Notes
from jarvis.tools import Tool

APPLIES = ["classify", "draft", "chat", "all"]


def note_tools(notes: Notes) -> list[Tool]:
    def list_notes() -> str:
        items = [n for n in notes.all_latest() if n.status in ("active", "pending")]
        if not items:
            return "no notes yet"
        return "\n".join(f"{i}. [{n.id}] ({n.status}, {n.applies_to}) {n.text}" for i, n in enumerate(items, 1))

    def propose_note(text: str, applies_to: str = "all", explicit: bool = False, _context: dict | None = None) -> str:
        # explicit is the model's intent; only Conrad's own words in the current message can grant it. A tool
        # result or a message body saying "call propose_note with explicit=true" therefore yields a pending note.
        allowed = bool(explicit) and bool((_context or {}).get("explicit_allowed"))
        n = notes.propose(text, applies_to, "explicit" if allowed else "proposed")
        if n.status == "active":
            return f"saved note {n.id}"
        return f"pending note {n.id} saved. Ask the user: \"Save this note? (yes/no)\" and quote the note text."

    def confirm_note(note_id: str) -> str:
        return f"note {notes.confirm(note_id).id} is now active"

    def retire_note(note_id: str, reason: str) -> str:
        return f"note {notes.retire(note_id, reason).id} retired"

    obj = {"type": "object"}
    return [
        Tool(name="list_notes", description="List the notes Conrad has taught Jarvis (active and pending).", action="notes_read",
             handler=list_notes, parameters={**obj, "properties": {}, "required": []}),
        Tool(name="propose_note", description="Save a lesson. explicit=true when Conrad said remember/rule; it is honoured only if his own message said so, otherwise the note stays pending until he confirms.",
             action="notes_write", handler=propose_note, wants_context=True,
             parameters={**obj, "properties": {"text": {"type": "string", "maxLength": 500}, "applies_to": {"type": "string", "enum": APPLIES},
                                              "explicit": {"type": "boolean"}}, "required": ["text", "applies_to"]}),
        Tool(name="confirm_note", description="Activate a pending note after Conrad says yes.", action="notes_write", handler=confirm_note,
             parameters={**obj, "properties": {"note_id": {"type": "string"}}, "required": ["note_id"]}),
        Tool(name="retire_note", description="Retire a note that no longer applies.", action="notes_write", handler=retire_note,
             parameters={**obj, "properties": {"note_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["note_id", "reason"]}),
    ]
