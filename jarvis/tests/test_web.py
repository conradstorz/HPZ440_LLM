import threading

import pytest
from fastapi.testclient import TestClient

from jarvis.briefing import Briefing
from jarvis.core.nko import NKOStatus, effective_group
from jarvis.core.run import RunSummary
from jarvis.journal import Journal
from jarvis.web import create_app
from tests.conftest import classified, make_nko


@pytest.fixture
def client(data_dir, store):
    n = classified(make_nko("gmail:a:1", subject="Hello there"), "fyi")
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

    app = create_app(store=store, journal=journal, briefing=Briefing(store, journal), run=run, llm_reachable=lambda: True)
    c = TestClient(app)
    c.gate, c.calls, c.store = gate, calls, store
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
