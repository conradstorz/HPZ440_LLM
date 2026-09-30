from datetime import UTC, datetime, timedelta

import pytest

from jarvis.journal import Journal
from jarvis.notes import Note, Notes


@pytest.fixture
def notes(data_dir):
    return Notes(data_dir, Journal(data_dir))


def test_explicit_is_active_and_proposed_is_pending(notes, data_dir):
    a = notes.propose("Invoices from Acme are mine to approve.", "classify", "explicit")
    b = notes.propose("Bob prefers short replies.", "draft", "proposed")
    assert a.status == "active" and b.status == "pending" and len(a.id) == 8 and a.version == 0
    assert [n.id for n in notes.active("classify")] == [a.id]
    assert notes.active("draft") == []
    assert (data_dir / "notes" / "notes.jsonl").read_text(encoding="utf-8").count("\n") == 2
    kinds = [e.kind for e in Journal(data_dir).iter_all()]
    assert kinds == ["note", "note"]


def test_confirm_and_retire_create_versions(notes):
    b = notes.propose("Bob prefers short replies.", "draft", "proposed")
    b2 = notes.confirm(b.id)
    assert b2.status == "active" and b2.version == 1
    assert [n.id for n in notes.active("draft")] == [b.id]
    b3 = notes.retire(b.id, "no longer true")
    assert b3.status == "retired" and b3.version == 2 and b3.reason == "no longer true"
    assert notes.active("draft") == [] and notes.get(b.id).version == 2
    with pytest.raises(ValueError):
        notes.confirm(b.id)
    with pytest.raises(KeyError):
        notes.retire("nope", "x")


def test_all_applies_to_everywhere_and_ordering(notes):
    n1 = notes.propose("Always be brief.", "all", "explicit")
    n2 = notes.propose("Classify newsletters as noise.", "classify", "explicit")
    assert [n.id for n in notes.active("classify")] == [n1.id, n2.id]
    assert [n.id for n in notes.active("chat")] == [n1.id]
    assert [n.id for n in notes.active("all")] == [n1.id, n2.id]


def test_render_for_prompt(notes):
    assert notes.render_for_prompt("chat") == ""
    notes.propose("Always be brief.", "all", "explicit")
    notes.propose("pending one", "chat", "proposed")
    text = notes.render_for_prompt("chat")
    assert text.startswith("Notes from Conrad:") and "1. Always be brief." in text and "pending one" not in text


def test_text_is_truncated_and_expire_pending(notes):
    n = notes.propose("x" * 600, "chat", "explicit")
    assert len(n.text) == 500
    old = notes.propose("stale", "chat", "proposed")
    now = datetime.now(tz=UTC) + timedelta(days=2)
    assert notes.expire_pending(now=now) == 1
    assert notes.get(old.id).status == "retired" and notes.get(old.id).reason == "expired"


def test_all_latest_and_reload(data_dir):
    j = Journal(data_dir)
    a = Notes(data_dir, j).propose("keep", "all", "explicit")
    fresh = Notes(data_dir, j)
    assert [n.id for n in fresh.all_latest()] == [a.id]
