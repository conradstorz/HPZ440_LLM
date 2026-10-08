from datetime import timedelta

import pytest

from obiwan.auth import Gate
from obiwan.inbox import Inbox
from obiwan.projection import FtsProjection
from obiwan.record import Record
from obiwan.service import Service
from obiwan.work import WorkQueue
from tests.conftest import T0


@pytest.fixture
def svc(settings):
    r = Record(settings.record_path)
    service = Service(settings, record=r, work=WorkQueue(r), projection=FtsProjection(settings.index_dir, r), inbox=Inbox(settings.inbox_dir),
                      gate=Gate(r, settings), now=lambda: T0)
    yield service
    service.projection.close()
    service.record.close()


def test_scan_then_search_returns_provenance_and_coverage(svc, corpus):
    rep = svc.scan(role="writer")
    assert rep["roots"][0]["reachable"] and rep["roots"][0]["new"] == 3 and rep["work"]["completed"] == 3
    out = svc.search("serengeti zebras", k=5)
    assert out["query"] == "serengeti zebras"
    top = out["results"][0]
    assert top["origin"] == "source" and top["attestation"] is None and top["location"] == "corpus:zebra.md"
    assert top["root"] == "corpus" and top["path"] == "zebra.md" and top["version_no"] == 1
    assert {"chunk_id", "doc_id", "subject_id", "seq", "start_char", "end_char", "score", "snippet", "content", "title"} <= set(top)
    cov = out["coverage"]
    assert cov["documents"] == cov["documents_indexed"] == 3 and cov["work_pending"] == 0 and cov["work_failed"] == 0
    assert cov["roots"] == [{"name": "corpus", "path": str(corpus), "reachable": True, "last_scan_at": T0.isoformat()}]
    assert cov["complete"] is True and cov["last_scan_at"] == T0.isoformat()
    assert svc.record.last_scan()["scan_id"] == rep["scan_id"]
    assert [e.kind for e in svc.record.events(limit=1)] == ["scan"]


def test_coverage_is_honest_when_work_is_pending_or_a_root_is_gone(svc, settings, tmp_path):
    svc.scan(role="writer")
    settings.source_roots = f"corpus={tmp_path / 'unmounted'}"
    rep = svc.scan(role="writer")
    assert rep["roots"][0]["reachable"] is False
    cov = svc.search("zebras", k=5)["coverage"]
    assert cov["complete"] is False and cov["roots"][0]["reachable"] is False
    assert cov["documents"] == 3  # nothing was marked deleted because a mount was absent


def test_submit_is_machine_and_search_labels_it(svc):
    out = svc.submit(content="Conrad probably prefers zebras to giraffes.", title="inference", role="writer")
    assert out["origin"] == "machine" and out["attestation"] is None and out["version_no"] == 1
    hit = svc.search("zebras giraffes", k=5)["results"][0]
    assert hit["origin"] == "machine" and hit["location"] == f"machine:{out['subject_id']}" and hit["root"] is None
    assert svc.record.events(limit=1)[0].kind == "accepted" and svc.record.events(limit=1)[0].role == "writer"
    with pytest.raises(ValueError):
        svc.submit(content="   ", title=None, role="writer")
    with pytest.raises(ValueError):
        svc.submit(content="x" * (svc.settings.max_submit_chars + 1), title=None, role="writer")


def test_relay_then_confirm_promotes_with_both_rungs_visible(svc):
    relayed = svc.relay(content="The NAS lives in the basement.", conversation_ref="chat-77", title=None, role="writer")
    assert relayed["origin"] == "human" and relayed["attestation"] == "relayed"
    hit = svc.search("basement NAS", k=5)["results"][0]
    assert (hit["origin"], hit["attestation"]) == ("human", "relayed")
    promoted = svc.confirm(subject_id=relayed["subject_id"], role="commander")
    assert promoted["attestation"] == "direct" and promoted["version_no"] == 2 and promoted["promoted_from"] == relayed["doc_id"]
    hit = svc.search("basement NAS", k=5)["results"]
    assert len(hit) == 1 and (hit[0]["origin"], hit[0]["attestation"], hit[0]["version_no"]) == ("human", "direct", 2)
    doc = svc.document(promoted["doc_id"])
    assert [(v["version_no"], v["attestation"]) for v in doc["versions"]] == [(1, "relayed"), (2, "direct")]
    assert doc["document"]["conversation_ref"] == "chat-77" and doc["content"] == "The NAS lives in the basement."
    assert svc.record.events(limit=1)[0].kind == "promotion"
    with pytest.raises(ValueError):
        svc.confirm(subject_id=relayed["subject_id"], role="commander")  # already direct
    with pytest.raises(KeyError):
        svc.confirm(subject_id="nope", role="commander")


def test_a_machine_record_cannot_be_promoted(svc):
    out = svc.submit(content="a guess", title=None, role="writer")
    with pytest.raises(ValueError, match="human"):
        svc.confirm(subject_id=out["subject_id"], role="commander")


def test_forget_leaves_a_tombstone_and_hides_the_subject(svc):
    out = svc.relay(content="Wrong fact about zebras.", conversation_ref="c1", title=None, role="writer")
    gone = svc.forget(subject_id=out["subject_id"], reason="mistaken", role="commander")
    assert gone["tombstone"]["reason"] == "mistaken" and gone["tombstone"]["ordered_by"] == "commander"
    assert svc.search("zebras", k=5)["results"] == []
    doc = svc.document(out["doc_id"])
    assert doc["tombstone"]["reason"] == "mistaken" and doc["chunks"][0]["projection_state"] == "stale"
    assert svc.coverage()["tombstoned"] == 1
    with pytest.raises(ValueError):
        svc.confirm(subject_id=out["subject_id"], role="commander")
    with pytest.raises(KeyError):
        svc.forget(subject_id="nope", reason="r", role="commander")


def test_document_view_for_a_source_file(svc):
    svc.scan(role="writer")
    hit = svc.search("invoice", k=1)["results"][0]
    view = svc.document(hit["doc_id"])
    assert view["document"]["origin"] == "source" and view["location"] == "corpus:invoice.txt"
    assert [s["path"] for s in view["sightings"]] == ["invoice.txt"]
    assert view["content"] is None and view["chunks"][0]["projection_state"] == "current"
    assert svc.document("missing") is None


def test_reindex_rebuilds_from_chunks_without_reading_sources(svc, corpus):
    svc.scan(role="writer")
    before = [r["chunk_id"] for r in svc.search("zebras invoice", k=10)["results"]]
    for p in corpus.rglob("*.md"):
        p.unlink()  # sources gone: a rebuild must not need them
    out = svc.reindex(role="writer")
    assert out["chunks_indexed"] >= 3
    assert [r["chunk_id"] for r in svc.search("zebras invoice", k=10)["results"]] == before
    assert svc.record.events(limit=1)[0].kind == "reindex"


def test_a_write_whose_journal_entry_fails_is_rolled_back_whole(svc, monkeypatch):
    def boom(kind, *, role=None, payload=None):
        raise RuntimeError("journal unavailable")

    monkeypatch.setattr(svc.record, "add_event", boom)
    with pytest.raises(RuntimeError):
        svc.submit(content="an inference that must not survive", title=None, role="writer")
    assert svc.record.latest_documents() == []
    assert svc.record.conn.execute("SELECT count(*) FROM texts").fetchone()[0] == 0


def test_a_failed_promotion_journal_entry_leaves_the_relayed_version_searchable(svc, monkeypatch):
    relayed = svc.relay(content="The NAS lives in the basement.", conversation_ref="chat-77", title=None, role="writer")
    hit = svc.search("basement NAS", k=5)["results"][0]
    assert hit["attestation"] == "relayed"

    def boom(kind, *, role=None, payload=None):
        raise RuntimeError("journal unavailable")

    monkeypatch.setattr(svc.record, "add_event", boom)
    with pytest.raises(RuntimeError):
        svc.confirm(subject_id=relayed["subject_id"], role="commander")

    doc = svc.document(relayed["doc_id"])
    assert len(doc["versions"]) == 1 and doc["versions"][0]["attestation"] == "relayed"
    hit = svc.search("basement NAS", k=5)["results"]
    assert len(hit) == 1 and hit[0]["attestation"] == "relayed"


def test_relay_without_a_conversation_ref_is_a_value_error(svc):
    with pytest.raises(ValueError):
        svc.relay(content="x", conversation_ref=None, title=None, role="writer")
    with pytest.raises(ValueError):
        svc.relay(content="x", conversation_ref="  ", title=None, role="writer")


def test_coverage_names_a_terminally_failed_document(settings, corpus):
    (corpus / "bad.pdf").write_bytes(b"not a pdf at all")
    clock = [T0]
    r = Record(settings.record_path)
    service = Service(settings, record=r, work=WorkQueue(r), projection=FtsProjection(settings.index_dir, r), inbox=Inbox(settings.inbox_dir),
                      gate=Gate(r, settings), now=lambda: clock[0])
    try:
        for _ in range(settings.max_attempts):
            service.scan(role="writer")
            clock[0] = clock[0] + timedelta(days=2)
        cov = service.coverage()
        assert cov["documents_failed"] == 1
        assert cov["work_failed"] == 1
        assert cov["complete"] is False
    finally:
        service.projection.close()
        service.record.close()


def test_status_and_journal(svc, inbox_dir):
    (inbox_dir / "drop.md").write_text("dropped zebra note\n", encoding="utf-8")
    (inbox_dir / "bad.pdf").write_bytes(b"nope")
    svc.scan(role="writer")
    st = svc.status()
    assert st["inbox"] == {"pending": 0, "failed": 1}
    assert st["coverage"]["documents"] == 4 and st["work"] == {"pending": 0, "failed": 0, "done": 3}
    assert st["last_scan"]["inbox"]["recorded"] == 1 and st["projection"] == {"current": st["coverage"]["chunks"]}
    kinds = [e["kind"] for e in svc.journal(limit=50)]
    assert "inbox_failed" in kinds and "inbox_recorded" in kinds and kinds[0] == "scan"
