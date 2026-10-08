import sqlite3

import pytest

from obiwan.chunking import chunk_text
from obiwan.projection import FtsProjection
from obiwan.record import Record
from tests.conftest import T0


@pytest.fixture
def world(data_dir):
    r = Record(data_dir / "record.sqlite")
    p = FtsProjection(data_dir / "index", r)
    yield r, p
    try:
        p.close()
    except sqlite3.ProgrammingError:
        pass
    r.close()


def _doc(r, p, subject, text, title="t"):
    d = r.add_document(subject_id=subject, origin="source", content_hash=text, media_type="text/plain", created_at=T0, title=title)
    chunks = r.add_chunks(d.doc_id, chunk_text(text, chunk_chars=200))
    p.index_document(d, chunks, now=T0)
    return d, chunks


def test_index_and_search_rank_by_bm25_with_snippets(world):
    r, p = world
    _doc(r, p, "f1", "Zebras migrate across the Serengeti.")
    _doc(r, p, "f2", "Invoice 42 is due Friday.")
    hits = p.search("zebra serengeti", k=5)
    assert len(hits) == 1 and hits[0].chunk_id.endswith("-0") and "Serengeti" in hits[0].snippet and hits[0].score > 0
    assert p.search("", k=5) == [] and p.search("x", k=5) == []
    assert p.count() == 2
    assert p.state_counts() == {"current": 2}


def test_a_new_version_supersedes_the_old_one_in_search(world):
    r, p = world
    old, old_chunks = _doc(r, p, "f1", "The plan mentions zebras.")
    new, _ = _doc(r, p, "f1", "The plan mentions giraffes now.")
    assert [h.chunk_id for h in p.search("zebras", k=5)] == []
    assert [h.chunk_id for h in p.search("giraffes", k=5)] == [f"{new.doc_id}-0"]
    states = dict(r.conn.execute("SELECT chunk_id, state FROM projection").fetchall())
    assert states[old_chunks[0].chunk_id] == "stale" and states[f"{new.doc_id}-0"] == "current"
    assert r.conn.execute("SELECT reason FROM projection WHERE chunk_id = ?", (old_chunks[0].chunk_id,)).fetchone()[0] == "superseded"
    assert p.state_counts() == {"current": 1, "stale": 1}


def test_retire_subject_removes_it_from_search_and_marks_stale(world):
    r, p = world
    d, chunks = _doc(r, p, "m1", "A machine conclusion about zebras.")
    r.add_tombstone(subject_id="m1", reason="wrong", ordered_by="commander", created_at=T0)
    p.retire_subject("m1", reason="forgotten", now=T0)
    assert p.search("zebras", k=5) == []
    assert r.conn.execute("SELECT state, reason FROM projection WHERE chunk_id = ?", (chunks[0].chunk_id,)).fetchone() == ("stale", "forgotten")


def test_rebuild_from_the_record_restores_identical_results_without_touching_sources(world, data_dir):
    r, p = world
    _doc(r, p, "f1", "Zebras migrate across the Serengeti.")
    _doc(r, p, "f1", "Zebras migrate across the Serengeti every year.")
    _doc(r, p, "f2", "Invoice 42 is due Friday.")
    _doc(r, p, "m1", "Forgotten conclusion about invoices.")
    r.add_tombstone(subject_id="m1", reason="r", ordered_by="commander", created_at=T0)
    p.retire_subject("m1", reason="forgotten", now=T0)
    before = [(h.chunk_id, h.snippet) for h in p.search("zebras invoice", k=10)]
    assert len(before) == 2
    assert p.rebuild(now=T0) == 2
    assert [(h.chunk_id, h.snippet) for h in p.search("zebras invoice", k=10)] == before
    assert p.state_counts() == {"current": 2, "stale": 2}
    # the projection file is disposable: delete it and reopen
    p.close()
    (data_dir / "index" / "fts.sqlite").unlink()
    p2 = FtsProjection(data_dir / "index", r)
    assert p2.count() == 0
    assert p2.rebuild(now=T0) == 2
    assert [(h.chunk_id, h.snippet) for h in p2.search("zebras invoice", k=10)] == before
    p2.close()


def test_a_corrupt_projection_file_is_discarded_on_open(data_dir):
    r = Record(data_dir / "record.sqlite")
    (data_dir / "index").mkdir()
    (data_dir / "index" / "fts.sqlite").write_bytes(b"not a database")
    p = FtsProjection(data_dir / "index", r)
    assert p.count() == 0
    p.close()
    r.close()


def test_reindexing_the_same_document_does_not_duplicate_rows(world):
    r, p = world
    d, chunks = _doc(r, p, "f1", "Zebras.")
    p.index_document(d, chunks, now=T0)
    assert p.count() == 1 and p.state_counts() == {"current": 1}
