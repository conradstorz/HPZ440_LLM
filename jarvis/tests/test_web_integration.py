"""The web app driving the real pipeline. TestClient runs sync handlers in a worker thread, so POST /run
exercises the SQLite index from a thread other than the one that built it."""

from fastapi.testclient import TestClient

from jarvis.briefing import Briefing
from jarvis.core.config import Settings
from jarvis.core.llm import FakeLLM
from jarvis.core.nko import utcnow
from jarvis.core.store import Store
from jarvis.journal import Journal
from jarvis.pipeline import run_once
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.sources.base import FakeSource
from jarvis.web import create_app
from tests.conftest import make_nko

CLS = {"group": "reply_suggested", "topic": "t", "requested_action": "reply", "deadline": None, "priority": "normal", "reasoning": "r"}
DRF = {"reply_text": "ok", "proposed_action": "none", "rationale": "r"}
# FakeSource filters on ``since``, so the fixtures must be inside the default lookback window.
NOW = utcnow()


def test_post_run_drives_the_real_pipeline_from_a_worker_thread(data_dir):
    store = Store(data_dir)
    journal = Journal(data_dir)
    policy = Policy(journal)
    index = Index(data_dir, store)
    briefing = Briefing(store, journal)
    settings = Settings(data_dir=data_dir)
    keys = ["gmail:a:1", "gmail:a:2"]
    source = FakeSource([make_nko(keys[0], subject="First subject", received_at=NOW),
                         make_nko(keys[1], subject="Second subject", received_at=NOW)])
    llm = FakeLLM([CLS, DRF, CLS, DRF])

    def run():
        return run_once(sources=[source], llm=llm, store=store, journal=journal, index=index, policy=policy,
                        briefing=briefing, settings=settings)

    client = TestClient(create_app(store=store, journal=journal, briefing=briefing, run=run,
                                   llm_reachable=lambda: True))

    r = client.post("/run", follow_redirects=False)
    assert r.status_code == 303

    for key in keys:
        assert store.get_latest(key).version == 2
    assert [e for e in journal.iter_all() if e.kind == "error"] == []

    body = client.get("/").text
    # group headings are the <h2>s; the plain titles also appear in every card's correction <select>
    assert "<h2>Reply suggested (2)</h2>" in body
    start = body.index("<h2>Reply suggested (2)</h2>")
    end = body.index("<h2>For your information (0)</h2>")
    for subject in ("First subject", "Second subject"):
        assert start < body.index(subject) < end
