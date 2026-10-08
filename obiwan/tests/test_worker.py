import shutil
from datetime import timedelta

import pytest

from obiwan.projection import FtsProjection
from obiwan.record import Record
from obiwan.scanner import scan_root
from obiwan.work import WorkQueue, backoff
from obiwan.worker import drain
from tests.conftest import T0


@pytest.fixture
def world(data_dir, settings, corpus):
    r = Record(data_dir / "record.sqlite")
    w = WorkQueue(r)
    p = FtsProjection(data_dir / "index", r)
    scan_root("corpus", corpus, record=r, work=w, scan_id="s1", now=T0, max_file_bytes=settings.max_file_bytes)
    yield r, w, p
    p.close()
    r.close()


def test_drain_extracts_chunks_and_indexes_every_pending_document(world, settings, corpus):
    r, w, p = world
    rep = drain(record=r, work=w, projection=p, roots={"corpus": corpus}, settings=settings, now=T0)
    assert (rep.completed, rep.failed, rep.postponed) == (3, 0, 0)
    assert w.counts() == {"pending": 0, "failed": 0, "done": 3}
    cov = r.coverage_counts()
    assert cov["documents"] == cov["documents_indexed"] == 3 and cov["chunks"] == cov["chunks_indexed"] >= 3
    hits = p.search("serengeti", k=5)
    assert hits and r.document(r.chunk(hits[0].chunk_id).doc_id).title == "zebra.md"


def test_an_unavailable_root_postpones_instead_of_failing(world, settings, tmp_path):
    r, w, p = world
    rep = drain(record=r, work=w, projection=p, roots={"corpus": tmp_path / "unmounted"}, settings=settings, now=T0)
    assert (rep.completed, rep.failed, rep.postponed) == (0, 0, 3)
    assert w.counts()["pending"] == 3
    item = w.claim(now=T0 + backoff(1), lease_seconds=1)
    assert item.attempts == 1 and item.last_error.startswith("RootUnavailable")
    assert r.coverage_counts()["chunks"] == 0  # nothing partial reached the record
    assert [e.kind for e in r.events(limit=10)] == ["work_failed"] * 3


def test_content_changed_since_scan_is_postponed_and_a_rescan_records_the_new_version(world, settings, corpus):
    r, w, p = world
    (corpus / "zebra.md").write_text("changed after the scan\n", encoding="utf-8", newline="\n")
    rep = drain(record=r, work=w, projection=p, roots={"corpus": corpus}, settings=settings, now=T0)
    assert (rep.completed, rep.postponed) == (2, 1)
    scan_root("corpus", corpus, record=r, work=w, scan_id="s2", now=T0 + timedelta(minutes=1), max_file_bytes=settings.max_file_bytes)
    rep = drain(record=r, work=w, projection=p, roots={"corpus": corpus}, settings=settings, now=T0 + backoff(1))
    assert rep.completed == 1 and rep.postponed in (0, 1)  # the v1 item may retry and fail again on the changed bytes; v2 succeeds
    assert p.search("changed", k=5)


def test_repeated_failures_become_failed_after_max_attempts(world, settings, tmp_path):
    r, w, p = world
    now = T0
    for _ in range(settings.max_attempts):
        drain(record=r, work=w, projection=p, roots={"corpus": tmp_path / "unmounted"}, settings=settings, now=now)
        now = now + timedelta(days=2)
    assert w.counts() == {"pending": 0, "failed": 3, "done": 0}


def test_a_reclaimed_item_whose_chunks_already_exist_does_not_duplicate_them(world, settings, corpus):
    r, w, p = world
    item = w.claim(now=T0, lease_seconds=1)  # simulate a crash after chunks were written but before complete()
    doc = r.document(item.target)
    from obiwan.chunking import chunk_text
    from obiwan.extract import extract_text
    sighting = r.latest_sighting(doc.subject_id)
    r.add_chunks(doc.doc_id, chunk_text(extract_text(corpus / sighting.path, max_pdf_pages=5), chunk_chars=settings.chunk_chars))
    n = len(r.chunks_for(doc.doc_id))
    rep = drain(record=r, work=w, projection=p, roots={"corpus": corpus}, settings=settings, now=T0 + timedelta(seconds=2))
    assert rep.completed == 3 and len(r.chunks_for(doc.doc_id)) == n
