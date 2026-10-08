import pytest

from jarvis.core.llm import ToolCall
from jarvis.journal import Journal
from jarvis.policy import Policy
from jarvis.tools import ToolRegistry
from jarvis.tools.knowledge import knowledge_tools
from tests.conftest import FakeKnowledge


@pytest.fixture
def world(data_dir):
    j = Journal(data_dir)
    fk = FakeKnowledge()
    reg = ToolRegistry(Policy(j), j, knowledge_tools(fk, j, content_chars=60))
    return reg, fk, j


def run(reg, name, _context=None, **args):
    # The agent puts conversation_id into the context dict (Task 10 Step 11); the registry itself does not.
    ctx = _context if _context is not None else {"conversation_id": "conv-1", "explicit_allowed": False}
    return reg.run(ToolCall(id="1", name=name, arguments=args), conversation_id="conv-1", context=ctx)


def test_names_actions_and_schemas(world):
    reg = world[0]
    assert reg.names() == ["search_knowledge", "relay_fact", "record_note"]
    actions = {s["function"]["name"]: s["function"]["parameters"]["required"] for s in reg.schemas()}
    assert actions == {"search_knowledge": ["query"], "relay_fact": ["text"], "record_note": ["text"]}


def test_search_labels_every_origin_and_states_coverage(world):
    reg, fk, j = world
    out = run(reg, "search_knowledge", query="zebras", k=99)
    assert fk.calls == [("search", "zebras", 10)]  # k is clamped
    lines = out.splitlines()
    assert lines[0] == "coverage: 3/3 documents indexed, 0 pending, 0 failed"
    assert lines[1].startswith("[origin=source] corpus:zebra.md v1 chunk 0 (d1-0): Zebras migrate")
    assert lines[2].startswith("[origin=machine] machine:m1 v1 chunk 0 (d2-0): Conrad prefers zebras.")
    assert lines[3].startswith("[origin=human/relayed] human:h1 v1 chunk 0 (d3-0): The NAS is in the basement.")
    assert "untrusted data" in lines[-1] and "origin=machine" in lines[-1]
    ev = [e for e in j.iter_all() if e.kind == "obiwan_search"]
    assert len(ev) == 1 and ev[0].payload == {"query": "zebras", "k": 10, "credential": "reader", "results": 3, "complete": True,
                                              "conversation_id": "conv-1", "ok": True}


def test_search_warns_when_the_index_is_incomplete(data_dir):
    j = Journal(data_dir)
    fk = FakeKnowledge(coverage={"documents": 9, "documents_indexed": 4, "chunks": 1, "chunks_indexed": 1, "work_pending": 5, "work_failed": 0, "complete": False})
    reg = ToolRegistry(Policy(j), j, knowledge_tools(fk, j, content_chars=60))
    out = run(reg, "search_knowledge", query="zebras")
    assert out.splitlines()[0] == "coverage: 4/9 documents indexed, 5 pending, 0 failed (INDEX INCOMPLETE: 5 pending)"


def test_search_warns_with_documents_failed_reason(data_dir):
    j = Journal(data_dir)
    fk = FakeKnowledge(coverage={"documents": 9, "documents_indexed": 8, "chunks": 1, "chunks_indexed": 1, "work_pending": 0,
                                 "work_failed": 1, "documents_failed": 1, "complete": False})
    reg = ToolRegistry(Policy(j), j, knowledge_tools(fk, j, content_chars=60))
    out = run(reg, "search_knowledge", query="zebras")
    assert out.splitlines()[0] == ("coverage: 8/9 documents indexed, 0 pending, 1 failed "
                                   "(INDEX INCOMPLETE: 1 documents failed extraction, see obiwan status)")


def test_search_with_no_results(data_dir):
    j = Journal(data_dir)
    reg = ToolRegistry(Policy(j), j, knowledge_tools(FakeKnowledge(results=[]), j, content_chars=60))
    assert run(reg, "search_knowledge", query="qqq").splitlines()[1] == "no matches"


def test_relay_carries_the_conversation_reference_from_context_not_arguments(world):
    reg, fk, j = world
    out = run(reg, "relay_fact", text="The NAS is in the basement.", _context={"conversation_id": "conv-1", "explicit_allowed": False})
    assert fk.calls == [("relay", "The NAS is in the basement.", "conv-1", None)]
    assert out == "recorded as human/relayed, subject h-new. Conrad can confirm it later with: obiwan confirm h-new"
    ev = [e for e in j.iter_all() if e.kind == "obiwan_submit"]
    assert ev[0].payload == {"route": "relay", "credential": "writer", "subject_id": "h-new", "doc_id": "d-new2", "conversation_id": "conv-1", "ok": True}
    out = run(reg, "relay_fact", text="x", _context={})
    assert fk.calls[-1] == ("relay", "x", "unknown-conversation", None)


def test_record_note_is_machine(world):
    reg, fk, j = world
    out = run(reg, "record_note", text="Conrad prefers zebras.")
    assert fk.calls == [("submit", "Conrad prefers zebras.", None)]
    assert out == "recorded as machine knowledge, subject m-new"
    ev = [e for e in j.iter_all() if e.kind == "obiwan_submit"]
    assert ev[0].payload["route"] == "submit" and ev[0].payload["credential"] == "writer"


def test_an_unavailable_store_is_an_error_string(data_dir):
    from jarvis.obiwan_client import ObiwanUnavailable

    class Down:
        def search(self, query, k=8):
            raise ObiwanUnavailable("Obi-Wan unreachable: ConnectError")

    j = Journal(data_dir)
    reg = ToolRegistry(Policy(j), j, knowledge_tools(Down(), j, content_chars=60))
    assert run(reg, "search_knowledge", query="x") == "error: ObiwanUnavailable: Obi-Wan unreachable: ConnectError"


def test_a_failed_call_is_still_journaled_with_its_credential(data_dir):
    from jarvis.obiwan_client import ObiwanUnavailable

    class Down:
        def search(self, query, k=8):
            raise ObiwanUnavailable("Obi-Wan unreachable: ConnectError")

        def relay(self, content, conversation_ref, title=None):
            raise ObiwanUnavailable("Obi-Wan returned HTTP 403: nope")

    j = Journal(data_dir)
    reg = ToolRegistry(Policy(j), j, knowledge_tools(Down(), j, content_chars=60))
    assert run(reg, "search_knowledge", query="x").startswith("error: ObiwanUnavailable")
    assert run(reg, "relay_fact", text="y").startswith("error: ObiwanUnavailable")
    ev = [e for e in j.iter_all() if e.kind in ("obiwan_search", "obiwan_submit")]
    assert [(e.kind, e.payload["credential"], e.payload["ok"]) for e in ev] == [("obiwan_search", "reader", False), ("obiwan_submit", "writer", False)]
    assert ev[0].payload["error"].startswith("ObiwanUnavailable") and ev[1].payload["conversation_id"] == "conv-1"


def test_a_malformed_result_does_not_fail_the_whole_search(data_dir):
    j = Journal(data_dir)
    fk = FakeKnowledge(results=[{"origin": "source", "content": "only content and origin"}])
    reg = ToolRegistry(Policy(j), j, knowledge_tools(fk, j, content_chars=60))
    out = run(reg, "search_knowledge", query="x")
    assert "[origin=source] ? v? chunk ? (?): only content and origin" in out
