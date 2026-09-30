import pytest

from jarvis.briefing import Briefing
from jarvis.core.llm import ToolCall
from jarvis.core.nko import GROUPS, NKOStatus
from jarvis.journal import Journal
from jarvis.notes import Notes
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.tools.registry import build_registry
from tests.conftest import FakeWorkspace, classified, make_nko


@pytest.fixture
def world(data_dir, store):
    j = Journal(data_dir)
    idx = Index(data_dir, store)
    b = Briefing(store, j)
    notes = Notes(data_dir, j)
    for i, g in enumerate(["needs_decision", "fyi", "likely_noise"]):
        n = make_nko(f"gmail:a:{i}", subject=f"Subject {i} zebra{i}", content=f"body {i}")
        store.save_version(n)
        idx.index(n)
        n = classified(n, g)
        store.save_version(n)
        n = n.derive(recommendations=[{"reply_text": "Hi" if g == "needs_decision" else None, "proposed_action": "none",
                                       "rationale": "r", "model": "fake", "at": "t"}], status=NKOStatus.DRAFTED)
        store.save_version(n)
    ws = FakeWorkspace()
    reg = build_registry(Policy(j), j, store=store, index=idx, briefing=b, notes=notes, workspace=ws, content_chars=50)
    return reg, store, notes, ws, j


def run(reg, name, **args):
    return reg.run(ToolCall(id="1", name=name, arguments=args))


def test_registry_names(world):
    reg = world[0]
    assert reg.names() == ["search_mail", "get_message", "briefing", "correct", "list_notes", "propose_note", "confirm_note",
                           "retire_note", "list_documents", "read_document"]


def test_search_and_get(world):
    reg = world[0]
    out = run(reg, "search_mail", query="zebra1")
    assert out.startswith("gmail:a:1 |") and "Subject 1" in out and "alice@example.com" in out
    assert run(reg, "search_mail", query="qqqq") == "no matches"
    msg = run(reg, "get_message", dedup_key="gmail:a:0")
    for label in ("From:", "Subject:", "Body", "Classification:", "Draft:"):
        assert label in msg
    assert "needs_decision" in msg and "Hi" in msg
    assert run(reg, "get_message", dedup_key="gmail:a:99").startswith("error: KeyError")


def test_briefing_tool(world):
    reg = world[0]
    out = run(reg, "briefing")
    assert out.startswith("needs_decision 1, reply_suggested 0, fyi 1, likely_noise 1")
    assert "Subject 0" in out and "Subject 2" in out
    only = run(reg, "briefing", group="fyi")
    assert "Subject 1" in only and "Subject 0" not in only
    assert run(reg, "briefing", group="spam").startswith("error: ValueError")


def test_correct_tool(world):
    reg, store = world[0], world[1]
    out = run(reg, "correct", dedup_key="gmail:a:1", to_group="needs_decision", note="matters")
    assert out == "gmail:a:1 moved fyi -> needs_decision (version 3)"
    assert store.get_latest("gmail:a:1").decisions[-1]["note"] == "matters"


def test_note_tools(world):
    reg, notes = world[0], world[2]
    assert run(reg, "list_notes") == "no notes yet"
    out = run(reg, "propose_note", text="Always be brief.", applies_to="all", explicit=True)
    nid = out.split()[-1]
    assert out.startswith("saved note") and notes.get(nid).status == "active"
    out2 = run(reg, "propose_note", text="Bob likes short replies.", applies_to="draft", explicit=False)
    pid = out2.split()[2]
    assert "Save this note?" in out2 and notes.get(pid).status == "pending"
    assert "pending" in run(reg, "list_notes") and "Always be brief." in run(reg, "list_notes")
    assert run(reg, "confirm_note", note_id=pid) == f"note {pid} is now active"
    assert run(reg, "retire_note", note_id=nid, reason="changed my mind") == f"note {nid} retired"
    assert run(reg, "confirm_note", note_id="zzzz").startswith("error: KeyError")


def test_nullable_params_use_anyof(world):
    schemas = {s["function"]["name"]: s["function"]["parameters"] for s in world[0].schemas()}
    assert schemas["briefing"]["properties"]["group"]["anyOf"] == [{"type": "string", "enum": list(GROUPS)}, {"type": "null"}]
    assert schemas["correct"]["properties"]["note"]["anyOf"][1] == {"type": "null"}


def test_document_tools(world):
    reg, ws = world[0], world[3]
    out = run(reg, "list_documents", glob="*.md")
    assert out.startswith("abc123def456 | C:/Docs | notes.md | 9 |") and ws.calls[0] == ("list", "*.md")
    doc = run(reg, "read_document", sha256="abc123def456")
    assert doc.startswith("notes.md (C:/Docs, 9 bytes)") and "hello doc" in doc
    ws.text = "x" * 200
    assert len(run(reg, "read_document", sha256="abc123def456")) < 120  # content_chars=50 cap plus header
    ws.text = None
    assert "no text extracted" in run(reg, "read_document", sha256="abc123def456")
