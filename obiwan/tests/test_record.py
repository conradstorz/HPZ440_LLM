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
    record.add_exclusion(doc_id=d.doc_id, reason="r", ordered_by="commander", created_at=T0)


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
    assert cov == {"documents": 1, "documents_indexed": 0, "chunks": 2, "chunks_indexed": 1, "tombstoned": 1, "documents_failed": 0,
                   "documents_excluded": 0}
    record.conn.execute("INSERT INTO projection(chunk_id, kind, state) VALUES (?, 'fts', 'current')", (f"{b.doc_id}-1",))
    assert record.coverage_counts()["documents_indexed"] == 1


# ----- schema version check and migration seam -----

def _user_version(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def _at_version_1(path):
    """A file the seam tests treat as schema 1: today's shape, stamped 1, so a monkeypatched step 2 is what runs."""
    Record(path).close()
    c = sqlite3.connect(path)
    try:
        c.execute("PRAGMA user_version = 1")
    finally:
        c.close()


def test_fresh_record_gets_current_schema_version(data_dir):
    from obiwan.record.schema import SCHEMA_VERSION
    r = Record(data_dir / "record.sqlite")
    r.close()
    assert _user_version(data_dir / "record.sqlite") == SCHEMA_VERSION


def test_reopening_current_version_journals_no_migration(data_dir):
    Record(data_dir / "record.sqlite").close()
    r = Record(data_dir / "record.sqlite")
    try:
        assert r.events(kind="schema_migrated") == []
    finally:
        r.close()


def test_newer_record_is_refused_and_left_untouched(data_dir):
    from obiwan.record.schema import SCHEMA_VERSION
    path = data_dir / "record.sqlite"
    Record(path).close()
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    c.close()
    with pytest.raises(RuntimeError, match=rf"schema {SCHEMA_VERSION + 1}.*understands {SCHEMA_VERSION}"):
        Record(path)
    assert _user_version(path) == SCHEMA_VERSION + 1


def test_older_record_runs_migration_steps_and_journals(data_dir, monkeypatch):
    import obiwan.record as rec
    path = data_dir / "record.sqlite"
    _at_version_1(path)
    monkeypatch.setattr(rec, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(rec, "MIGRATIONS", {2: ("CREATE TABLE migrated_probe (x INTEGER)",)})
    r = Record(path)
    try:
        assert r.conn.execute("SELECT name FROM sqlite_master WHERE name = 'migrated_probe'").fetchone() is not None
        evs = r.events(kind="schema_migrated")
        assert len(evs) == 1 and evs[0].payload == {"from": 1, "to": 2}
    finally:
        r.close()
    assert _user_version(path) == 2
    r = Record(path)
    try:
        assert len(r.events(kind="schema_migrated")) == 1
    finally:
        r.close()


def test_failing_step_rolls_back_and_retry_succeeds(data_dir, monkeypatch):
    import obiwan.record as rec
    path = data_dir / "record.sqlite"
    _at_version_1(path)
    monkeypatch.setattr(rec, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(rec, "MIGRATIONS", {2: ("CREATE TABLE half_done (x INTEGER)", "THIS IS NOT SQL")})
    with pytest.raises(sqlite3.Error):
        Record(path)
    assert _user_version(path) == 1
    c = sqlite3.connect(path)
    try:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name = 'half_done'").fetchone() is None
        assert c.execute("SELECT count(*) FROM events WHERE kind = 'schema_migrated'").fetchone()[0] == 0
    finally:
        c.close()
    monkeypatch.setattr(rec, "MIGRATIONS", {2: ("CREATE TABLE half_done (x INTEGER)",)})
    r = Record(path)
    try:
        assert len(r.events(kind="schema_migrated")) == 1
    finally:
        r.close()
    assert _user_version(path) == 2


def test_span_applies_every_step(data_dir, monkeypatch):
    import obiwan.record as rec
    path = data_dir / "record.sqlite"
    _at_version_1(path)
    monkeypatch.setattr(rec, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(rec, "MIGRATIONS", {2: ("CREATE TABLE p2 (x INTEGER)",), 3: ("CREATE TABLE p3 (x INTEGER)",)})
    r = Record(path)
    try:
        names = {row[0] for row in r.conn.execute("SELECT name FROM sqlite_master WHERE name IN ('p2', 'p3')")}
        assert names == {"p2", "p3"}
        assert sorted((e.payload["from"], e.payload["to"]) for e in r.events(kind="schema_migrated")) == [(1, 2), (2, 3)]
    finally:
        r.close()
    assert _user_version(path) == 3


def test_missing_migration_step_raises_and_leaves_file(data_dir, monkeypatch):
    import obiwan.record as rec
    path = data_dir / "record.sqlite"
    _at_version_1(path)
    monkeypatch.setattr(rec, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(rec, "MIGRATIONS", {3: ("CREATE TABLE p3 (x INTEGER)",)})
    with pytest.raises(RuntimeError, match="step 2"):
        Record(path)
    assert _user_version(path) == 1


# ----- exclusions (v0.1.1): a Commander-ordered, append-only mark on one failed document version -----

def _v1_schema_sql() -> str:
    """The record exactly as schema 1 shipped it: every table and trigger except exclusions."""
    from obiwan.record.schema import EXCLUSIONS_TABLE, SCHEMA, TRIGGERS
    assert EXCLUSIONS_TABLE in SCHEMA
    triggers = "\n".join(line for line in TRIGGERS.splitlines() if " ON exclusions " not in line)
    return SCHEMA.replace(EXCLUSIONS_TABLE, "") + triggers


def test_schema_version_is_2_and_exclude_is_a_commander_only_power():
    from obiwan.record.schema import MIGRATIONS, SCHEMA_VERSION
    assert SCHEMA_VERSION == 2 and set(MIGRATIONS) == {2}
    assert "exclude" in POWERS["commander"]
    assert "exclude" not in POWERS["writer"] and "exclude" not in POWERS["reader"]


def test_a_version_1_record_file_migrates_to_2_with_an_append_only_exclusions_table(data_dir):
    path = data_dir / "record.sqlite"
    c = sqlite3.connect(path)
    c.executescript(_v1_schema_sql())
    c.execute("INSERT INTO documents(doc_id, subject_id, version_no, origin, content_hash, media_type, created_at) "
              "VALUES ('d1', 's1', 1, 'source', 'h', 'text/plain', '2026-10-07T12:00:00+00:00')")
    c.execute("INSERT INTO powers(role, power, granted_at) VALUES ('commander', 'forget', 'then')")
    c.execute("PRAGMA user_version = 1")
    c.commit()
    assert c.execute("SELECT 1 FROM sqlite_master WHERE name = 'exclusions'").fetchone() is None
    c.close()
    r = Record(path)
    try:
        assert _user_version(path) == 2
        names = {row[0] for row in r.conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'exclusions%'")}
        assert names == {"exclusions", "exclusions_no_update", "exclusions_no_delete"}
        evs = r.events(kind="schema_migrated")
        assert len(evs) == 1 and evs[0].payload == {"from": 1, "to": 2}
        assert "exclude" in r.powers_for("commander") and "exclude" not in r.powers_for("writer")
        assert r.document("d1").subject_id == "s1"  # what was there is still there
        r.add_exclusion(doc_id="d1", reason="corrupt scan", ordered_by="commander", created_at=T0)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            r.conn.execute("UPDATE exclusions SET reason = 'other'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            r.conn.execute("DELETE FROM exclusions")
    finally:
        r.close()


def test_migration_step_2_builds_the_table_and_triggers_on_its_own():
    """On a real open SCHEMA creates the table first; this proves the step alone is sufficient and idempotent."""
    from obiwan.record.schema import MIGRATIONS
    c = sqlite3.connect(":memory:")
    try:
        c.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
        for _ in range(2):
            for stmt in MIGRATIONS[2]:
                c.execute(stmt)
        c.execute("INSERT INTO documents VALUES ('d1')")
        c.execute("INSERT INTO exclusions(doc_id, reason, ordered_by, created_at) VALUES ('d1', 'r', 'commander', 't')")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute("UPDATE exclusions SET reason = 'x'")
    finally:
        c.close()


def test_exclusion_round_trip_is_one_per_document(record):
    d = _source_doc(record)
    assert record.exclusion_for(d.doc_id) is None
    e = record.add_exclusion(doc_id=d.doc_id, reason="unreadable scan", ordered_by="commander", created_at=T0)
    got = record.exclusion_for(d.doc_id)
    assert got == e and (got.doc_id, got.reason, got.ordered_by) == (d.doc_id, "unreadable scan", "commander")
    with pytest.raises(sqlite3.IntegrityError):
        record.add_exclusion(doc_id=d.doc_id, reason="again", ordered_by="commander", created_at=T0)
    with pytest.raises(sqlite3.IntegrityError):
        record.add_exclusion(doc_id="no-such-doc", reason="r", ordered_by="commander", created_at=T0)


def _failed(record, kind, target):
    record.conn.execute("INSERT INTO work(kind, target, state, attempts, next_attempt_at, created_at, updated_at) "
                        "VALUES (?, ?, 'failed', 5, 't', 't', 't')", (kind, target))


def test_an_excluded_latest_version_is_neither_failed_nor_blocking(record):
    good = _source_doc(record, "f1", "h1")
    record.add_chunks(good.doc_id, [ChunkSpec(0, 0, 1, "a")])
    record.conn.execute("INSERT INTO projection(chunk_id, kind, state) VALUES (?, 'fts', 'current')", (f"{good.doc_id}-0",))
    bad = _source_doc(record, "f2", "h2")
    _failed(record, "extract", bad.doc_id)
    cov = record.coverage_counts()
    assert (cov["documents"], cov["documents_indexed"], cov["documents_failed"], cov["documents_excluded"]) == (2, 1, 1, 0)
    assert record.failed_work_blocking() == 1
    record.add_exclusion(doc_id=bad.doc_id, reason="r", ordered_by="commander", created_at=T0)
    cov = record.coverage_counts()
    assert (cov["documents"], cov["documents_indexed"], cov["documents_failed"], cov["documents_excluded"]) == (2, 1, 0, 1)
    assert record.failed_work_blocking() == 0
    newer = _source_doc(record, "f2", "h3")  # a changed file is a new version, tried fresh: not excluded
    cov = record.coverage_counts()
    assert (cov["documents"], cov["documents_failed"], cov["documents_excluded"]) == (2, 0, 0)
    _failed(record, "extract", newer.doc_id)
    assert record.coverage_counts()["documents_failed"] == 1 and record.failed_work_blocking() == 1


@pytest.mark.parametrize("kind", ["extract", "index"])
def test_failed_work_on_a_superseded_or_forgotten_version_does_not_block(record, kind):
    old = _source_doc(record, "f1", "h1")
    _failed(record, kind, old.doc_id)
    assert record.failed_work_blocking() == 1
    _source_doc(record, "f1", "h2")
    assert record.failed_work_blocking() == 0  # superseded
    gone = _source_doc(record, "f2", "h3")
    _failed(record, kind, gone.doc_id)
    assert record.failed_work_blocking() == 1
    record.add_tombstone(subject_id="f2", reason="r", ordered_by="commander", created_at=T0)
    assert record.failed_work_blocking() == 0  # forgotten
