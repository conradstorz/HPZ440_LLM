import shutil
from datetime import timedelta

import pytest

from obiwan.record import Record
from obiwan.scanner import scan_root, scan_roots
from obiwan.work import WorkQueue
from tests.conftest import T0


@pytest.fixture
def world(data_dir):
    r = Record(data_dir / "record.sqlite")
    yield r, WorkQueue(r)
    r.close()


def _scan(world, corpus, scan_id, now=T0):
    r, w = world
    return scan_root("corpus", corpus, record=r, work=w, scan_id=scan_id, now=now, max_file_bytes=1_000_000)


def test_first_scan_records_every_supported_file_once(world, corpus):
    r, w = world
    rep = _scan(world, corpus, "s1")
    assert rep.reachable and rep.error is None
    assert (rep.seen, rep.new, rep.unchanged, rep.changed, rep.moved, rep.duplicates) == (3, 3, 0, 0, 0, 0)
    assert rep.skipped_unsupported == 1  # image.png
    docs = r.latest_documents()
    assert len(docs) == 3 and all(d.origin == "source" and d.version_no == 1 for d in docs)
    assert {r.latest_sighting(d.subject_id).path for d in docs} == {"zebra.md", "invoice.txt", "notes/plan.md"}
    assert w.counts()["pending"] == 3
    assert r.document(docs[0].doc_id).title in {"zebra.md", "invoice.txt", "notes/plan.md"}


def test_rescan_unchanged_is_idempotent(world, corpus):
    r, w = world
    _scan(world, corpus, "s1")
    rep = _scan(world, corpus, "s2", now=T0 + timedelta(hours=1))
    assert (rep.new, rep.unchanged, rep.changed, rep.moved) == (0, 3, 0, 0)
    assert len(r.latest_documents()) == 3 and all(d.version_no == 1 for d in r.latest_documents())
    assert w.counts()["pending"] == 3  # nothing re-enqueued
    f = r.latest_documents()[0].subject_id
    assert [s.scan_id for s in r.sightings_for(f)] == ["s1", "s2"]  # last_seen_at is the latest sighting


def test_a_changed_file_becomes_a_new_version_of_the_same_file(world, corpus):
    r, w = world
    _scan(world, corpus, "s1")
    before = {r.latest_sighting(d.subject_id).path: d for d in r.latest_documents()}
    (corpus / "zebra.md").write_text("# Zebra migration\n\nZebras migrate across the Serengeti every year, in July.\n", encoding="utf-8", newline="\n")
    rep = _scan(world, corpus, "s2")
    assert (rep.new, rep.unchanged, rep.changed) == (0, 2, 1)
    zebra = before["zebra.md"]
    latest = r.latest_document(zebra.subject_id)
    assert latest.version_no == 2 and latest.content_hash != zebra.content_hash and latest.doc_id != zebra.doc_id
    assert len(r.documents_for(zebra.subject_id)) == 2
    assert w.counts()["pending"] == 4


def test_a_moved_file_keeps_its_identity_and_gets_no_new_version(world, corpus):
    r, w = world
    _scan(world, corpus, "s1")
    zebra = next(d for d in r.latest_documents() if r.latest_sighting(d.subject_id).path == "zebra.md")
    (corpus / "archive").mkdir()
    (corpus / "zebra.md").rename(corpus / "archive" / "zebra-2026.md")
    rep = _scan(world, corpus, "s2")
    assert (rep.new, rep.unchanged, rep.moved, rep.changed) == (0, 2, 1, 0)
    assert r.latest_sighting(zebra.subject_id).path == "archive/zebra-2026.md"
    assert r.latest_document(zebra.subject_id).doc_id == zebra.doc_id
    assert len(r.latest_documents()) == 3


def test_an_identical_copy_is_a_second_file_with_the_duplication_noted(world, corpus):
    r, w = world
    _scan(world, corpus, "s1")
    zebra = next(d for d in r.latest_documents() if r.latest_sighting(d.subject_id).path == "zebra.md")
    shutil.copyfile(corpus / "zebra.md", corpus / "zebra-copy.md")
    rep = _scan(world, corpus, "s2")
    assert (rep.new, rep.duplicates, rep.moved) == (0, 1, 0)
    copy = next(d for d in r.latest_documents() if r.latest_sighting(d.subject_id).path == "zebra-copy.md")
    assert copy.subject_id != zebra.subject_id and r.file(copy.subject_id).duplicate_of == zebra.subject_id
    assert len(r.latest_documents()) == 4


def test_moved_and_edited_is_recorded_as_a_new_file_the_known_limit(world, corpus):
    r, w = world
    _scan(world, corpus, "s1")
    (corpus / "zebra.md").rename(corpus / "zebra-v2.md")
    (corpus / "zebra-v2.md").write_text("# Zebra migration\n\nEdited after the move.\n", encoding="utf-8", newline="\n")
    rep = _scan(world, corpus, "s2")
    assert (rep.new, rep.moved, rep.changed) == (1, 0, 0)
    assert len(r.latest_documents()) == 4  # the old file_id still points at zebra.md, which no longer resolves


def test_an_unreachable_root_is_a_gap_and_nothing_is_touched(world, corpus, tmp_path):
    r, w = world
    _scan(world, corpus, "s1")
    n_sightings = r.conn.execute("SELECT count(*) FROM sightings").fetchone()[0]
    rep = scan_root("corpus", tmp_path / "unmounted", record=r, work=w, scan_id="s2", now=T0, max_file_bytes=1_000_000)
    assert rep.reachable is False and rep.error and rep.seen == 0
    assert r.conn.execute("SELECT count(*) FROM sightings").fetchone()[0] == n_sightings
    assert len(r.latest_documents()) == 3
    rep = _scan(world, corpus, "s3")  # a later scan completes the work
    assert rep.reachable and rep.unchanged == 3


def test_scan_roots_handles_each_root_independently(world, corpus, tmp_path):
    r, w = world
    reps = scan_roots({"corpus": corpus, "gone": tmp_path / "gone"}, record=r, work=w, scan_id="s1", now=T0, max_file_bytes=1_000_000)
    assert [(x.name, x.reachable) for x in reps] == [("corpus", True), ("gone", False)]


def test_files_over_the_size_limit_are_skipped_and_counted(world, corpus):
    r, w = world
    (corpus / "big.txt").write_text("x" * 5000, encoding="utf-8")
    rep = scan_root("corpus", corpus, record=r, work=w, scan_id="s1", now=T0, max_file_bytes=4000)
    assert rep.skipped_large == 1 and rep.new == 3
