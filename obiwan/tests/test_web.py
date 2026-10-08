import pytest
from fastapi.testclient import TestClient

from obiwan.runtime import build_service
from obiwan.web import create_app

R, W, C = {"Authorization": "Bearer r-token"}, {"Authorization": "Bearer w-token"}, {"Authorization": "Bearer c-token"}


@pytest.fixture
def client(settings):
    svc = build_service(settings)
    with TestClient(create_app(svc)) as c:
        c.svc = svc
        yield c
    svc.projection.close()
    svc.record.close()


def test_health_needs_no_credential(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["documents"] == 0


def test_every_other_route_refuses_a_missing_or_unknown_credential(client):
    for method, path in (("get", "/search?q=x"), ("get", "/document/x"), ("get", "/status"), ("get", "/journal"),
                         ("post", "/submit"), ("post", "/relay"), ("post", "/confirm"), ("post", "/scan"), ("post", "/reindex")):
        # httpx's get()/TestClient.get() has no `json` parameter (body-bearing kwargs are deliberately
        # omitted from the GET convenience method in every httpx version); it is only meaningful on POST.
        kw = {"json": {}} if method == "post" else {}
        assert getattr(client, method)(path, **kw).status_code == 401, path
        assert getattr(client, method)(path, **kw, headers={"Authorization": "Bearer nope"}).status_code == 401, path
    assert [e.kind for e in client.svc.record.events(limit=100)] == ["refused"] * 18


def test_reader_cannot_write_and_writer_cannot_confirm(client):
    assert client.post("/submit", json={"content": "x"}, headers=R).status_code == 403
    assert client.post("/scan", headers=R).status_code == 403
    assert client.post("/confirm", json={"subject_id": "s"}, headers=W).status_code == 403  # S7: the proposer is not the reviewer
    assert client.post("/confirm", json={"subject_id": "s", "action": "forget", "reason": "r"}, headers=W).status_code == 403


def test_scan_search_document_status_journal(client, corpus):
    r = client.post("/scan", headers=W)
    assert r.status_code == 200 and r.json()["work"]["completed"] == 3
    r = client.get("/search", params={"q": "serengeti", "k": 3}, headers=R)
    body = r.json()
    assert r.status_code == 200 and body["results"][0]["location"] == "corpus:zebra.md" and body["coverage"]["complete"] is True
    doc_id = body["results"][0]["doc_id"]
    r = client.get(f"/document/{doc_id}", headers=R)
    assert r.status_code == 200 and r.json()["document"]["origin"] == "source" and r.json()["sightings"][0]["path"] == "zebra.md"
    assert client.get("/document/nope", headers=R).status_code == 404
    assert client.get("/status", headers=R).json()["coverage"]["documents"] == 3
    assert client.get("/journal", params={"limit": 5}, headers=R).json()[0]["kind"] == "scan"
    assert client.get("/health").json()["documents"] == 3


def test_submit_is_machine_and_claimed_provenance_is_refused(client):
    r = client.post("/submit", json={"content": "an inference", "title": "t"}, headers=W)
    assert r.status_code == 200 and r.json()["origin"] == "machine" and r.json()["attestation"] is None
    r = client.post("/submit", json={"content": "an inference", "origin": "human"}, headers=W)
    assert r.status_code == 400 and "origin" in r.json()["detail"]
    r = client.post("/submit", json={"content": "x", "attestation": "direct"}, headers=W)
    assert r.status_code == 400
    assert client.post("/submit", json={"content": ""}, headers=W).status_code == 400
    assert client.post("/submit", json={"title": "no content"}, headers=W).status_code == 400
    assert client.post("/submit", json={"content": "x", "extra": 1}, headers=W).status_code == 400
    kinds = [e.kind for e in client.svc.record.events(limit=10, kind="refused")]
    assert len(kinds) == 2  # the two provenance claims; validation errors are not refusals


def test_relay_confirm_forget_flow_over_http(client):
    r = client.post("/relay", json={"content": "The NAS is in the basement.", "conversation_ref": "chat-1"}, headers=W)
    assert r.status_code == 200 and (r.json()["origin"], r.json()["attestation"]) == ("human", "relayed")
    sid = r.json()["subject_id"]
    assert client.post("/relay", json={"content": "no ref"}, headers=W).status_code == 400
    r = client.post("/confirm", json={"subject_id": sid}, headers=C)
    assert r.status_code == 200 and r.json()["attestation"] == "direct" and r.json()["version_no"] == 2
    assert client.post("/confirm", json={"subject_id": sid}, headers=C).status_code == 409  # already direct
    assert client.post("/confirm", json={"subject_id": "nope"}, headers=C).status_code == 404
    hits = client.get("/search", params={"q": "basement"}, headers=R).json()["results"]
    assert len(hits) == 1 and hits[0]["attestation"] == "direct"
    r = client.post("/confirm", json={"subject_id": sid, "action": "forget", "reason": "moved house"}, headers=C)
    assert r.status_code == 200 and r.json()["tombstone"]["reason"] == "moved house"
    assert client.get("/search", params={"q": "basement"}, headers=R).json()["results"] == []
    assert client.post("/confirm", json={"subject_id": sid, "action": "forget"}, headers=C).status_code == 400  # reason required


def test_reindex_and_scan_lock(client, monkeypatch):
    client.post("/scan", headers=W)
    r = client.post("/reindex", headers=W)
    assert r.status_code == 200 and r.json()["chunks_indexed"] >= 3
    lock = client.app.state.maintenance_lock
    assert lock.acquire(blocking=False)
    try:
        assert client.post("/scan", headers=W).status_code == 409
        assert client.post("/reindex", headers=W).status_code == 409
    finally:
        lock.release()


def test_a_non_object_body_is_400_not_422(client):
    assert client.post("/submit", json=[1, 2, 3], headers=W).status_code == 400
    assert client.post("/relay", json="text", headers=W).status_code == 400
    assert client.post("/confirm", json=[], headers=C).status_code == 400
