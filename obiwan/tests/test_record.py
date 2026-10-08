import sqlite3
import threading

import pytest

from obiwan.chunking import ChunkSpec
from obiwan.record import APPEND_ONLY, POWERS, Record
from tests.conftest import T0


@pytest.fixture
def record(data_dir):
    # Deviation from the brief: the brief's Record.close() is never wired into this fixture,
    # so every test leaves an unclosed sqlite3.Connection. CPython's GC later emits
    # ResourceWarning: unclosed database, pytest's unraisableexception plugin turns that into
    # PytestUnraisableExceptionWarning, and this project's filterwarnings=["error", ...] turns
    # that into a test failure -- attributed nondeterministically to whichever test happens to
    # be running when garbage collection fires (observed on two different tests across two runs
    # with identical code). Closing the connection on teardown removes the leak; no assertion
    # in any test changes.
    r = Record(data_dir / "record.sqlite")
    yield r
    r.close()


def _source_doc(record, subject="f1", h="h1"):
    return record.add_document(subject_id=subject, origin="source", content_hash=h, media_type="text/markdown",
                               created_at=T0, title="a.md", scan_id="s1")


def test_a_write_from_another_thread_is_not_swallowed_by_an_open_transaction(record):
    started, done = threading.Event(), threading.Event()

    def other_thread():
        started.set()
        record.add_event("accepted", role="writer", payload={"from": "other thread"})
        done.set()

    t = threading.Thread(target=other_thread)
    with pytest.raises(RuntimeError):
        with record.transaction():
            _source_doc(record)
            t.start()
            started.wait(timeout=5)
            assert not done.wait(timeout=0.2)  # blocked on the lock, not folded into this transaction
            raise RuntimeError("roll back only this transaction")
    t.join(timeout=5)
    assert done.is_set()
    assert [e.payload for e in record.events(limit=5, kind="accepted")] == [{"from": "other thread"}]
    assert record.latest_documents() == []


def test_schema_is_created_with_powers_seeded(record):
    tables = {r[0] for r in record.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(APPEND_ONLY) | {"work", "projection"} <= tables
    assert record.powers_for("reader") == POWERS["reader"]
    assert record.powers_for("writer") == POWERS["writer"]
    assert record.powers_for("commander") == POWERS["commander"]
    assert POWERS["reader"] < POWERS["writer"] < POWERS["commander"]
    assert record.powers_for("nobody") == set()


def _populate_every_record_table(record):
    """Triggers fire per row, so every append-only table needs at least one row before UPDATE/DELETE can be refused."""
    f = record.mint_file(root="corpus", first_seen_at=T0)
    record.add_sighting(file_id=f, root="corpus", path="a.md", content_hash="h1", size=1, mtime="m", seen_at=T0, scan_id="s1")
    d = _source_doc(record, subject=f)
    record.add_text(d.doc_id, "text")
    record.add_chunks(d.doc_id, [ChunkSpec(0, 0, 4, "text")])
    record.add_tombstone(subject_id="gone", reason="r", ordered_by="commander", created_at=T0)
    record.add_event("accepted", role="writer", payload={})
    record.add_scan(scan_id="s1", started_at=T0, finished_at=T0, report={})


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_record_tables_refuse_update_and_delete(record, table):
    _populate_every_record_table(record)
    assert record.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= 1
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        record.conn.execute(f"DELETE FROM {table}")
    cols = [r[1] for r in record.conn.execute(f"PRAGMA table_info({table})")]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        record.conn.execute(f"UPDATE {table} SET {cols[-1]} = {cols[-1]}")


def test_document_versions_increment_per_subject(record):
    a = _source_doc(record, "f1", "h1")
    b = _source_doc(record, "f1", "h2")
    c = _source_doc(record, "f2", "h1")
    assert (a.version_no, b.version_no, c.version_no) == (1, 2, 1)
    assert record.latest_document("f1").doc_id == b.doc_id
    assert [d.doc_id for d in record.documents_for("f1")] == [a.doc_id, b.doc_id]
    assert {d.doc_id for d in record.latest_documents()} == {b.doc_id, c.doc_id}


def test_human_requires_attestation_and_others_refuse_it(record):
    with pytest.raises(sqlite3.IntegrityError):
        record.add_document(subject_id="h", origin="human", content_hash="x", media_type="text/plain", created_at=T0)
    with pytest.raises(sqlite3.IntegrityError):
        record.add_document(subject_id="m", origin="machine", attestation="direct", content_hash="x", media_type="text/plain", created_at=T0)
    with pytest.raises(sqlite3.IntegrityError):
        record.add_document(subject_id="m", origin="oracle", content_hash="x", media_type="text/plain", created_at=T0)
    d = record.add_document(subject_id="h", origin="human", attestation="relayed", content_hash="x", media_type="text/plain",
                            created_at=T0, submitted_by="writer", conversation_ref="conv-1")
    assert d.origin == "human" and d.attestation == "relayed" and d.conversation_ref == "conv-1"


def test_chunks_get_deterministic_ids_and_keep_position(record):
    d = _source_doc(record)
    chunks = record.add_chunks(d.doc_id, [ChunkSpec(0, 0, 5, "hello"), ChunkSpec(1, 7, 12, "world")])
    assert [c.chunk_id for c in chunks] == [f"{d.doc_id}-0", f"{d.doc_id}-1"]
    assert record.chunk(f"{d.doc_id}-1").start_char == 7
    assert [c.text for c in record.chunks_for(d.doc_id)] == ["hello", "world"]
    assert record.chunk_ids_for_subject("f1") == [f"{d.doc_id}-0", f"{d.doc_id}-1"]


def test_sightings_resolve_identity_by_path_and_hash(record):
    f = record.mint_file(root="corpus", first_seen_at=T0)
    record.add_sighting(file_id=f, root="corpus", path="a.md", content_hash="h1", size=5, mtime="2026-10-07T00:00:00+00:00", seen_at=T0, scan_id="s1")
    record.add_sighting(file_id=f, root="corpus", path="b/a.md", content_hash="h1", size=5, mtime="2026-10-07T00:00:00+00:00", seen_at=T0, scan_id="s2")
    assert record.latest_sighting(f).path == "b/a.md"
    assert record.latest_sighting_at("corpus", "a.md").scan_id == "s1"
    assert record.latest_sighting_at("corpus", "zzz") is None
    assert record.file_ids_with_hash("h1") == [f]
    assert record.file_ids_with_hash("nope") == []
    assert record.file(f).duplicate_of is None
    assert len(record.sightings_for(f)) == 2


def test_file_ids_with_hash_uses_only_the_latest_sighting(record):
    f = record.mint_file(root="corpus", first_seen_at=T0)
    record.add_sighting(file_id=f, root="corpus", path="a.md", content_hash="old", size=1, mtime="m", seen_at=T0, scan_id="s1")
    record.add_sighting(file_id=f, root="corpus", path="a.md", content_hash="new", size=1, mtime="m", seen_at=T0, scan_id="s2")
    assert record.file_ids_with_hash("old") == [] and record.file_ids_with_hash("new") == [f]


def test_text_tombstone_event_and_scan_round_trip(record):
    d = record.add_document(subject_id="m1", origin="machine", content_hash="x", media_type="text/plain", created_at=T0)
    record.add_text(d.doc_id, "a conclusion")
    assert record.text(d.doc_id) == "a conclusion" and record.text("missing") is None
    t = record.add_tombstone(subject_id="m1", reason="wrong", ordered_by="commander", created_at=T0)
    assert record.tombstone_for("m1").id == t.id and record.tombstone_for("f9") is None
    record.add_event("refused", role=None, payload={"power": "submit"})
    record.add_event("accepted", role="writer", payload={"route": "submit"})
    ev = record.events(limit=10)
    assert [e.kind for e in ev] == ["accepted", "refused"] and ev[0].role == "writer" and ev[1].payload == {"power": "submit"}
    assert record.events(limit=10, kind="refused")[0].role is None
    assert record.last_scan() is None
    record.add_scan(scan_id="s1", started_at=T0, finished_at=T0, report={"roots": []})
    assert record.last_scan()["scan_id"] == "s1" and record.last_scan()["report"] == {"roots": []}


def test_transaction_rolls_back_everything_on_error(record):
    with pytest.raises(RuntimeError):
        with record.transaction():
            _source_doc(record)
            raise RuntimeError("boom")
    assert record.latest_documents() == []
    with record.transaction():
        with record.transaction():  # nested: only the outermost commits
            _source_doc(record)
    assert len(record.latest_documents()) == 1


def test_coverage_counts_latest_non_tombstoned_only(record):
    a = _source_doc(record, "f1", "h1")
    record.add_chunks(a.doc_id, [ChunkSpec(0, 0, 1, "a")])
    b = _source_doc(record, "f1", "h2")
    record.add_chunks(b.doc_id, [ChunkSpec(0, 0, 1, "b"), ChunkSpec(1, 2, 3, "c")])
    c = _source_doc(record, "f2", "h3")
    record.add_chunks(c.doc_id, [ChunkSpec(0, 0, 1, "d")])
    record.add_tombstone(subject_id="f2", reason="r", ordered_by="commander", created_at=T0)
    record.conn.execute("INSERT INTO projection(chunk_id, kind, state) VALUES (?, 'fts', 'current')", (f"{b.doc_id}-0",))
    cov = record.coverage_counts()
    assert cov == {"documents": 1, "documents_indexed": 0, "chunks": 2, "chunks_indexed": 1, "tombstoned": 1, "documents_failed": 0}
    record.conn.execute("INSERT INTO projection(chunk_id, kind, state) VALUES (?, 'fts', 'current')", (f"{b.doc_id}-1",))
    assert record.coverage_counts()["documents_indexed"] == 1
