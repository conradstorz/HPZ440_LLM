"""mvp.md section 17, executed. Each test is one heading; they run in file order against one live service."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from obiwan.core.ids import sha256_file
from obiwan.runtime import build_service
from obiwan.web import create_app

R, W, C = {"Authorization": "Bearer r-token"}, {"Authorization": "Bearer w-token"}, {"Authorization": "Bearer c-token"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from obiwan.core.config import Settings

    base = tmp_path_factory.mktemp("e2e")
    corpus, inbox, data = base / "corpus", base / "inbox", base / "data"
    for d in (corpus, inbox, data, corpus / "notes"):
        d.mkdir()
    (corpus / "zebra.md").write_text("# Zebra migration\n\nZebras migrate across the Serengeti every year.\n", encoding="utf-8", newline="\n")
    (corpus / "invoice.txt").write_text("Invoice 42 is due on Friday. Approve the invoice before then.\n", encoding="utf-8", newline="\n")
    (corpus / "notes" / "plan.md").write_text("Plan\n\nMigrate the zebra photos to the NAS after the invoice is paid.\n", encoding="utf-8", newline="\n")
    settings = Settings(_env_file=None, data_dir=data, inbox_dir=inbox, source_roots=f"corpus={corpus}",
                        reader_token="r-token", writer_token="w-token", commander_token="c-token", chunk_chars=200)
    svc = build_service(settings)
    with TestClient(create_app(svc)) as client:
        yield {"client": client, "svc": svc, "corpus": corpus, "inbox": inbox, "settings": settings, "ids": {}}
    svc.projection.close()
    svc.record.close()


def _scan(w):
    r = w["client"].post("/scan", headers=W)
    assert r.status_code == 200, r.text
    return r.json()


def _search(w, q, k=5):
    r = w["client"].get("/search", params={"q": q, "k": k}, headers=R)
    assert r.status_code == 200, r.text
    return r.json()


def test_01_ingest(world):
    rep = _scan(world)
    root = rep["roots"][0]
    assert root["reachable"] and root["new"] == 3 and rep["work"]["completed"] == 3
    cov = _search(world, "zebra")["coverage"]
    assert cov["documents"] == cov["documents_indexed"] == 3 and cov["complete"] is True
    world["ids"]["zebra_doc"] = next(r for r in _search(world, "serengeti")["results"] if r["path"] == "zebra.md")


def test_02_reingest_is_idempotent(world):
    svc = world["svc"]
    docs_before = svc.record.conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    chunks_before = svc.record.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    rep = _scan(world)
    assert rep["roots"][0]["unchanged"] == 3 and rep["roots"][0]["new"] == 0 and rep["work"]["completed"] == 0
    assert svc.record.conn.execute("SELECT count(*) FROM documents").fetchone()[0] == docs_before
    assert svc.record.conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == chunks_before


def test_03_change_becomes_a_new_version_of_the_same_file(world):
    (world["corpus"] / "zebra.md").write_text("# Zebra migration\n\nZebras migrate across the Serengeti every July.\n", encoding="utf-8", newline="\n")
    rep = _scan(world)
    assert rep["roots"][0]["changed"] == 1 and rep["work"]["completed"] == 1
    old = world["ids"]["zebra_doc"]
    hits = _search(world, "serengeti")["results"]
    new = next(r for r in hits if r["path"] == "zebra.md")
    assert new["subject_id"] == old["subject_id"] and new["version_no"] == 2 and new["doc_id"] != old["doc_id"]
    assert "July" in new["content"] and all("every year" not in r["content"] for r in hits)
    view = world["client"].get(f"/document/{new['doc_id']}", headers=R).json()
    assert [v["version_no"] for v in view["versions"]] == [1, 2]


def test_04_move_keeps_identity(world):
    (world["corpus"] / "archive").mkdir()
    (world["corpus"] / "zebra.md").rename(world["corpus"] / "archive" / "zebra.md")
    rep = _scan(world)
    assert rep["roots"][0]["moved"] == 1 and rep["roots"][0]["new"] == 0
    hit = next(r for r in _search(world, "serengeti")["results"] if r["subject_id"] == world["ids"]["zebra_doc"]["subject_id"])
    assert hit["location"] == "corpus:archive/zebra.md" and hit["version_no"] == 2


def test_05_inbox_records_good_files_and_quarantines_bad_ones(world):
    inbox = world["inbox"]
    (inbox / "memo.md").write_text("# Memo\n\nThe giraffe enclosure opens in May.\n", encoding="utf-8", newline="\n")
    (inbox / "scan.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    rep = _scan(world)
    assert rep["inbox"]["recorded"] == 1 and rep["inbox"]["failed"] == 1
    assert not (inbox / "memo.md").exists() and any(p.name == "memo.md" for p in (inbox / "processed").rglob("*.md"))
    assert (inbox / "failed" / "scan.pdf").exists()
    err = json.loads((inbox / "failed" / "scan.pdf.error.json").read_text(encoding="utf-8"))
    assert err["error"].startswith("ExtractionError")
    hit = _search(world, "giraffe enclosure")["results"][0]
    assert hit["origin"] == "source" and hit["root"] == "inbox" and hit["location"].startswith("inbox:processed/")
    assert world["svc"].record.conn.execute("SELECT count(*) FROM documents WHERE title = 'scan.pdf'").fetchone()[0] == 0


def test_06_source_unavailable_is_a_gap_not_a_deletion(world):
    corpus = world["corpus"]
    hidden = corpus.with_name("corpus-hidden")
    corpus.rename(hidden)
    try:
        rep = _scan(world)
        assert rep["roots"][0]["reachable"] is False
        out = _search(world, "invoice")
        assert out["coverage"]["complete"] is False and out["coverage"]["roots"][0]["reachable"] is False
        assert out["coverage"]["documents"] == 4 and out["results"]  # untouched and still retrievable
    finally:
        hidden.rename(corpus)
    rep = _scan(world)
    assert rep["roots"][0]["reachable"] and rep["roots"][0]["unchanged"] == 3
    assert _search(world, "invoice")["coverage"]["complete"] is True


def test_07_retrieve_traces_answer_to_chunk_to_version_to_source_file(world):
    out = _search(world, "when is the invoice due")
    assert out["coverage"]["complete"] is True
    hit = next(r for r in out["results"] if r["path"] == "invoice.txt")
    assert "Friday" in hit["content"]
    view = world["client"].get(f"/document/{hit['doc_id']}", headers=R).json()
    chunk = next(c for c in view["chunks"] if c["chunk_id"] == hit["chunk_id"])
    assert chunk["projection_state"] == "current"
    root_name, rel = view["location"].split(":", 1)
    source = world["svc"].roots[root_name] / rel
    assert source.is_file() and sha256_file(source) == view["document"]["content_hash"]
    assert source.read_text(encoding="utf-8")[chunk["start_char"]:chunk["end_char"]] == chunk["text"]


def test_08_machine_write_is_labelled_and_cannot_claim_human(world):
    c = world["client"]
    r = c.post("/submit", json={"content": "Conrad seems to prefer zebras to giraffes.", "title": "inference"}, headers=W)
    assert r.status_code == 200 and r.json()["origin"] == "machine"
    world["ids"]["machine"] = r.json()["subject_id"]
    hit = next(x for x in _search(world, "prefer zebras giraffes")["results"] if x["subject_id"] == world["ids"]["machine"])
    assert hit["origin"] == "machine" and hit["attestation"] is None and hit["location"] == f"machine:{hit['subject_id']}"
    assert c.post("/submit", json={"content": "Conrad prefers zebras.", "origin": "human"}, headers=W).status_code == 400
    assert c.post("/submit", json={"content": "Conrad prefers zebras.", "attestation": "direct"}, headers=W).status_code == 400
    assert c.post("/confirm", json={"subject_id": world["ids"]["machine"]}, headers=C).status_code == 409  # machine stays machine


def test_09_human_write_relayed_then_confirmed_and_jarvis_is_refused_at_confirm(world):
    c = world["client"]
    r = c.post("/relay", json={"content": "The NAS lives in the basement rack.", "conversation_ref": "openwebui:chat-123"}, headers=W)
    assert r.status_code == 200 and (r.json()["origin"], r.json()["attestation"]) == ("human", "relayed")
    sid = r.json()["subject_id"]
    assert c.post("/confirm", json={"subject_id": sid}, headers=W).status_code == 403  # S7
    assert c.post("/confirm", json={"subject_id": sid}, headers=R).status_code == 403
    refused = [e for e in world["svc"].record.events(limit=5, kind="refused")]
    assert refused[0].role == "reader" and refused[1].role == "writer"
    r = c.post("/confirm", json={"subject_id": sid}, headers=C)
    assert r.status_code == 200 and r.json()["attestation"] == "direct" and r.json()["version_no"] == 2
    view = c.get(f"/document/{r.json()['doc_id']}", headers=R).json()
    assert [(v["version_no"], v["attestation"]) for v in view["versions"]] == [(1, "relayed"), (2, "direct")]
    assert view["versions"][1]["promotion_of"] == view["versions"][0]["doc_id"]
    hits = [x for x in _search(world, "basement rack")["results"] if x["subject_id"] == sid]
    assert len(hits) == 1 and hits[0]["attestation"] == "direct"
    world["ids"]["human"] = sid


def test_10_rebuild_from_stored_chunks_without_sources(world):
    before = sorted(r["chunk_id"] for r in _search(world, "zebra invoice basement giraffe", k=25)["results"])
    assert len(before) >= 5
    corpus = world["corpus"]
    stash = corpus.with_name("corpus-stash")
    shutil.copytree(corpus, stash)
    for p in corpus.rglob("*"):
        if p.is_file():
            p.unlink()  # every source gone; a rebuild must not need them
    try:
        r = world["client"].post("/reindex", headers=W)
        assert r.status_code == 200 and r.json()["chunks_indexed"] >= 5
        assert sorted(r["chunk_id"] for r in _search(world, "zebra invoice basement giraffe", k=25)["results"]) == before
    finally:
        shutil.rmtree(corpus)
        stash.rename(corpus)
    # forgetting still works after a rebuild and leaves its mark
    r = world["client"].post("/confirm", json={"subject_id": world["ids"]["human"], "action": "forget", "reason": "moved house"}, headers=C)
    assert r.status_code == 200
    assert all(x["subject_id"] != world["ids"]["human"] for x in _search(world, "basement rack")["results"])
    assert world["client"].get("/status", headers=R).json()["coverage"]["tombstoned"] == 1
