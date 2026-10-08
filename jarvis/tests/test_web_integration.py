"""The web app driving the real pipeline. TestClient runs sync handlers in a worker thread, so POST /run
exercises the SQLite index from a thread other than the one that built it."""

from fastapi.testclient import TestClient

from jarvis.agent import Agent
from jarvis.briefing import Briefing
from jarvis.core.config import Settings
from jarvis.core.llm import ChatTurn, FakeLLM, ToolCall
from jarvis.core.nko import utcnow
from jarvis.core.store import Store
from jarvis.journal import Journal
from jarvis.notes import Notes
from jarvis.pipeline import run_once
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.sources.base import FakeSource
from jarvis.tools.registry import build_registry
from jarvis.web import create_app
from tests.conftest import FakeKnowledge, FakeWorkspace, make_nko

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
                        briefing=briefing, notes=Notes(data_dir, journal), settings=settings)

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


def test_chat_endpoint_answers_from_the_real_tool_registry(data_dir):
    """A chat turn that calls search_mail through the real registry, served by the real app."""
    store = Store(data_dir)
    journal = Journal(data_dir)
    index = Index(data_dir, store)
    briefing = Briefing(store, journal)
    notes = Notes(data_dir, journal)
    n = make_nko("gmail:a:7", subject="Zebra invoice", content="The zebra invoice is due Friday.", received_at=NOW)
    store.save_version(n)
    index.index(n)
    tools = build_registry(Policy(journal), journal, store=store, index=index, briefing=briefing, notes=notes,
                           workspace=FakeWorkspace(), knowledge=FakeKnowledge(), content_chars=6000)
    llm = FakeLLM(turns=[ChatTurn(content="", tool_calls=[ToolCall(id="c1", name="search_mail", arguments={"query": "zebra"})],
                                  finish_reason="tool_calls"),
                         ChatTurn(content="Yes: gmail:a:7, the Zebra invoice, is due Friday.")])
    agent = Agent(llm, tools, notes, journal)
    client = TestClient(create_app(store=store, journal=journal, briefing=briefing, run=lambda: None,
                                   llm_reachable=lambda: True, notes=notes,
                                   respond=lambda messages, cid: agent.respond(messages, conversation_id=cid)))

    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "anything about the zebra invoice?"}],
                                                  "chat_id": "conv-1"})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Yes: gmail:a:7, the Zebra invoice, is due Friday."

    # the tool actually ran against the index and its result was fed back into the second model turn
    tool_msgs = [m for m in llm.chat_calls[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0]["name"] == "search_mail"
    assert "gmail:a:7" in tool_msgs[0]["content"] and "Zebra invoice" in tool_msgs[0]["content"]

    events = {e.kind: e for e in journal.iter_all()}
    assert events["tool_call"].payload["name"] == "search_mail" and events["tool_call"].payload["ok"] is True
    assert events["chat"].payload["tools_used"] == ["search_mail"] and events["chat"].payload["conversation_id"] == "conv-1"
    assert not [e for e in journal.iter_all() if e.kind == "policy_reject"]
