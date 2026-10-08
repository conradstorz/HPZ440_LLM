import json

import pytest

from obiwan.inbox import Inbox, process_inbox
from obiwan.projection import FtsProjection
from obiwan.record import Record
from tests.conftest import T0


@pytest.fixture
def world(data_dir, inbox_dir):
    r = Record(data_dir / "record.sqlite")
    p = FtsProjection(data_dir / "index", r)
    yield r, p, Inbox(inbox_dir)
    p.close()
    r.close()


def test_inbox_creates_its_subdirectories_and_lists_only_top_level_regular_files(inbox_dir):
    box = Inbox(inbox_dir)
    assert (inbox_dir / "processed").is_dir() and (inbox_dir / "failed").is_dir()
    (inbox_dir / "b.md").write_text("b", encoding="utf-8")
    (inbox_dir / "a.txt").write_text("a", encoding="utf-8")
    (inbox_dir / ".partial.md").write_text("x", encoding="utf-8")
    (inbox_dir / "c.md.tmp").write_text("x", encoding="utf-8")
    (inbox_dir / "processed" / "old.md").write_text("x", encoding="utf-8")
    assert [p.name for p in box.pending()] == ["a.txt", "b.md"]


def test_a_dropped_document_is_recorded_then_moved_to_processed(world, inbox_dir, settings):
    r, p, box = world
    (inbox_dir / "memo.md").write_text("# Memo\n\nThe zebra photos go on the NAS.\n", encoding="utf-8", newline="\n")
    rep = process_inbox(box, record=r, projection=p, settings=settings, scan_id="s1", now=T0)
    assert (rep.recorded, rep.failed) == (1, 0)
    dest = inbox_dir / "processed" / "2026-10-07" / "memo.md"
    assert dest.is_file() and not (inbox_dir / "memo.md").exists()
    doc = r.latest_documents()[0]
    assert doc.origin == "source" and doc.title == "memo.md" and r.file(doc.subject_id).root == "inbox"
    assert r.latest_sighting(doc.subject_id).path == "processed/2026-10-07/memo.md"
    assert p.search("zebra NAS", k=5)
    assert [e.kind for e in r.events(limit=5)] == ["inbox_recorded"]


def test_a_corrupt_file_moves_to_failed_with_the_reason_beside_it_and_nothing_reaches_the_record(world, inbox_dir, settings):
    r, p, box = world
    (inbox_dir / "scan.pdf").write_bytes(b"%PDF-1.4 garbage")
    (inbox_dir / "photo.png").write_bytes(b"\x89PNG")
    rep = process_inbox(box, record=r, projection=p, settings=settings, scan_id="s1", now=T0)
    assert (rep.recorded, rep.failed) == (0, 2)
    assert (inbox_dir / "failed" / "scan.pdf").is_file() and (inbox_dir / "failed" / "photo.png").is_file()
    err = json.loads((inbox_dir / "failed" / "scan.pdf.error.json").read_text(encoding="utf-8"))
    assert err["file"] == "scan.pdf" and err["error"].startswith("ExtractionError") and err["scan_id"] == "s1"
    assert json.loads((inbox_dir / "failed" / "photo.png.error.json").read_text(encoding="utf-8"))["error"].startswith("ExtractionError: unsupported")
    assert r.latest_documents() == [] and r.conn.execute("SELECT count(*) FROM files").fetchone()[0] == 0
    assert [e.kind for e in r.events(limit=5)] == ["inbox_failed", "inbox_failed"]


def test_name_collisions_in_processed_and_failed_get_a_numeric_suffix(world, inbox_dir, settings):
    r, p, box = world
    for text in ("first\n", "second\n"):
        (inbox_dir / "memo.md").write_text(text, encoding="utf-8", newline="\n")
        process_inbox(box, record=r, projection=p, settings=settings, scan_id="s1", now=T0)
    names = sorted(x.name for x in (inbox_dir / "processed" / "2026-10-07").iterdir())
    assert names == ["memo-1.md", "memo.md"]
    for _ in range(2):
        (inbox_dir / "bad.pdf").write_bytes(b"nope")
        process_inbox(box, record=r, projection=p, settings=settings, scan_id="s1", now=T0)
    assert sorted(x.name for x in (inbox_dir / "failed").iterdir()) == ["bad-1.pdf", "bad-1.pdf.error.json", "bad.pdf", "bad.pdf.error.json"]


def test_an_identical_drop_is_a_second_file_with_duplicate_noted(world, inbox_dir, settings):
    r, p, box = world
    (inbox_dir / "a.md").write_text("same bytes\n", encoding="utf-8", newline="\n")
    process_inbox(box, record=r, projection=p, settings=settings, scan_id="s1", now=T0)
    (inbox_dir / "b.md").write_text("same bytes\n", encoding="utf-8", newline="\n")
    process_inbox(box, record=r, projection=p, settings=settings, scan_id="s2", now=T0)
    docs = r.latest_documents()
    assert len(docs) == 2
    dup = next(d for d in docs if d.title == "b.md")
    assert r.file(dup.subject_id).duplicate_of == next(d for d in docs if d.title == "a.md").subject_id


def test_a_failed_move_leaves_the_file_pending_journals_it_and_continues(world, inbox_dir, settings, monkeypatch):
    from pathlib import Path

    r, p, box = world
    (inbox_dir / "a.md").write_text("first zebra note\n", encoding="utf-8", newline="\n")
    (inbox_dir / "b.md").write_text("second zebra note\n", encoding="utf-8", newline="\n")
    real_replace = Path.replace

    def flaky_replace(self, target):
        if self.name == "a.md":
            raise OSError(5, "simulated I/O error")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    rep = process_inbox(box, record=r, projection=p, settings=settings, scan_id="s1", now=T0)
    assert (rep.recorded, rep.failed) == (1, 1)
    assert (inbox_dir / "a.md").is_file()  # still pending at the top level, not quarantined
    docs = r.latest_documents()
    a_doc = next(d for d in docs if d.title == "a.md")
    assert sorted(d.title for d in docs) == ["a.md", "b.md"]  # the record DOES have a.md now
    assert r.latest_sighting(a_doc.subject_id).path == "processed/2026-10-07/a.md"
    ev = r.events(limit=5, kind="inbox_move_failed")[0]
    assert ev.payload["file"] == "a.md" and ev.payload["recorded_doc_id"] == a_doc.doc_id
    assert ev.payload["destination"] == "processed/2026-10-07/a.md"
    assert rep.failed == 1


def test_an_interrupted_move_is_completed_on_the_next_scan(world, inbox_dir, settings, monkeypatch):
    from pathlib import Path

    r, p, box = world
    (inbox_dir / "a.md").write_text("first zebra note\n", encoding="utf-8", newline="\n")
    (inbox_dir / "b.md").write_text("second zebra note\n", encoding="utf-8", newline="\n")
    real_replace = Path.replace

    def flaky_replace(self, target):
        if self.name == "a.md":
            raise OSError(5, "simulated I/O error")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    process_inbox(box, record=r, projection=p, settings=settings, scan_id="s1", now=T0)
    monkeypatch.undo()  # remove the flaky replace; the real Path.replace is restored

    rep = process_inbox(box, record=r, projection=p, settings=settings, scan_id="s2", now=T0)
    assert rep.recovered == 1
    a_doc = next(d for d in r.latest_documents() if d.title == "a.md")
    dest = inbox_dir / "processed" / "2026-10-07" / "a.md"
    assert dest.is_file() and not (inbox_dir / "a.md").exists()
    assert len(r.latest_documents()) == 2  # no new document was created, still exactly two
    assert r.events(limit=1)[0].kind == "inbox_move_completed"
