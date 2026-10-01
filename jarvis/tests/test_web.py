import threading

import pytest
from fastapi.testclient import TestClient

from jarvis.briefing import Briefing
from jarvis.core.nko import NKOStatus, effective_group
from jarvis.core.run import RunSummary
from jarvis.journal import Journal
from jarvis.notes import Notes
from jarvis.web import create_app
from tests.conftest import classified, make_nko


@pytest.fixture
def client(data_dir, store):
    n = make_nko("gmail:a:1", subject="Hello there")
    store.save_version(n)  # the real pipeline writes v0 first; Store.count() counts v0 directories
    n = classified(n, "fyi")
    store.save_version(n)
    n = n.derive(recommendations=[{"reply_text": None, "proposed_action": "none", "rationale": "r", "model": "rule", "at": "t"}], status=NKOStatus.DRAFTED)
    store.save_version(n)
    journal = Journal(data_dir)
    gate = threading.Event()
    calls = []

    def run():
        calls.append(1)
        gate.wait(timeout=5)
        from datetime import UTC, datetime
        return RunSummary(since=datetime(2025, 9, 1, tzinfo=UTC), captured=0)

    notes = Notes(data_dir, journal)
    app = create_app(store=store, journal=journal, briefing=Briefing(store, journal), run=run, llm_reachable=lambda: True,
                     notes=notes, respond=lambda m, cid: iter(["pong"]))
    c = TestClient(app)
    c.gate, c.calls, c.store, c.notes = gate, calls, store, notes
    return c


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    for h in ("Needs your decision", "Reply suggested", "For your information", "Likely noise"):
        assert h in r.text
    assert "Hello there" in r.text


def test_correct_redirects_and_moves_group(client):
    r = client.post("/correct", data={"dedup_key": "gmail:a:1", "to_group": "needs_decision", "note": "x"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert effective_group(client.store.get_latest("gmail:a:1")) == "needs_decision"


def test_message_page(client):
    r = client.get("/message/gmail:a:1")
    assert r.status_code == 200 and "Hello there" in r.text
    assert client.get("/message/gmail:a:nope").status_code == 404


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "llm": True, "messages": 1, "last_run": None}


def test_run_conflict_while_running(client):
    client.gate.clear()
    t = threading.Thread(target=lambda: client.post("/run", follow_redirects=False))
    t.start()
    import time
    for _ in range(50):
        if client.calls:
            break
        time.sleep(0.02)
    r = client.post("/run", follow_redirects=False)
    assert r.status_code == 409
    client.gate.set()
    t.join()
    assert client.get("/health").json()["last_run"] is None  # run() here is a stub that writes no journal event


def test_run_failure_is_journaled_and_surfaced(data_dir, store):
    journal = Journal(data_dir)

    def run():
        raise RuntimeError("no token")

    app = create_app(store=store, journal=journal, briefing=Briefing(store, journal), run=run,
                     llm_reachable=lambda: True)
    r = TestClient(app).post("/run", follow_redirects=False)
    assert r.status_code == 500
    assert "no token" in r.json()["detail"]
    errors = [e for e in journal.iter_all() if e.kind == "error"]
    assert len(errors) == 1 and errors[0].payload["stage"] == "run"


def test_notes_page_and_retire(client):
    n = client.notes.propose("Always be brief.", "all", "explicit")
    r = client.get("/notes")
    assert r.status_code == 200 and "Always be brief." in r.text and n.id in r.text and "Retire" in r.text
    r = client.post("/notes/retire", data={"note_id": n.id, "reason": "no"}, follow_redirects=False)
    assert r.status_code == 303 and client.notes.get(n.id).status == "retired"
    assert client.post("/notes/retire", data={"note_id": "zzzz", "reason": "no"}).status_code == 404


def test_retire_all_pending_from_the_notes_page(client):
    keep = client.notes.propose("Always be brief.", "all", "explicit")
    junk = [client.notes.propose(f"The tags for the chat history are: General. {i}", "chat", "proposed") for i in range(3)]
    assert "Retire all pending" in client.get("/notes").text
    r = client.post("/notes/retire-pending", data={"reason": "junk from task prompts"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/notes"
    assert all(client.notes.get(n.id).status == "retired" for n in junk)
    assert all(client.notes.get(n.id).reason == "junk from task prompts" for n in junk)
    assert client.notes.get(keep.id).status == "active"
    # the reason is optional, and an empty sweep is still a redirect, not an error
    assert client.post("/notes/retire-pending", data={}, follow_redirects=False).status_code == 303


def test_openai_routes_mounted(client):
    assert client.get("/v1/models").json()["data"][0]["id"] == "jarvis"
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "ping"}]})
    assert r.json()["choices"][0]["message"]["content"] == "pong"


def test_nav_links(client):
    assert 'href="/notes"' in client.get("/").text
