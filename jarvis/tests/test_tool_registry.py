import pytest

from jarvis.core.llm import ToolCall
from jarvis.journal import Journal
from jarvis.policy import Policy
from jarvis.tools import Tool, ToolRegistry


def _echo(text: str, times: int = 1) -> str:
    return text * times


def _boom(**kw) -> str:
    raise RuntimeError("kaput")


@pytest.fixture
def reg(data_dir):
    j = Journal(data_dir)
    r = ToolRegistry(Policy(j), j)
    r.register(Tool(name="echo", description="Echo text", action="read", handler=_echo, result_chars=10,
                    parameters={"type": "object", "properties": {"text": {"type": "string"}, "times": {"type": "integer"}}, "required": ["text"]}))
    r.register(Tool(name="boom", description="Fails", action="read", handler=_boom, parameters={"type": "object", "properties": {}}))
    r.register(Tool(name="forbidden", description="Outbound", action="send", handler=_echo, parameters={"type": "object", "properties": {}}))
    r.journal = j
    return r


def test_schemas_shape(reg):
    s = reg.schemas()
    assert s[0] == {"type": "function", "function": {"name": "echo", "description": "Echo text",
                    "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "times": {"type": "integer"}}, "required": ["text"]}}}
    assert reg.names() == ["echo", "boom", "forbidden"]


def test_run_success_truncates_and_journals(reg):
    out = reg.run(ToolCall(id="1", name="echo", arguments={"text": "abc", "times": 5}), conversation_id="conv1")
    assert out.startswith("abcabcabca") and out.endswith("[truncated]") and len(out) < 40
    ev = [e for e in reg.journal.iter_all() if e.kind == "tool_call"]
    assert ev[0].payload["name"] == "echo" and ev[0].payload["ok"] is True and ev[0].payload["conversation_id"] == "conv1"
    assert ev[0].payload["arguments"] == {"text": "abc", "times": 5}


def test_unknown_tool_and_raw_arguments_are_policy_rejects(reg):
    assert reg.run(ToolCall(id="1", name="nope", arguments={})).startswith("error: unknown tool")
    assert reg.run(ToolCall(id="2", name="echo", arguments={"_raw": "junk"})).startswith("error: invalid tool arguments")
    kinds = [e.kind for e in reg.journal.iter_all()]
    assert kinds == ["policy_reject", "policy_reject"]


def test_handler_error_and_policy_violation_become_error_strings(reg):
    assert reg.run(ToolCall(id="1", name="boom", arguments={})) == "error: RuntimeError: kaput"
    assert reg.run(ToolCall(id="2", name="forbidden", arguments={"text": "x"})).startswith("error: PolicyViolation")
    # echo's result_chars=10 truncates the full "error: TypeError: ..." message; this asserts the
    # truncated-but-still-diagnostic text rather than the untruncated exception string.
    assert reg.run(ToolCall(id="3", name="echo", arguments={"wrong": 1})).startswith("error: TypeError")
    ev = [e for e in reg.journal.iter_all() if e.kind == "tool_call"]
    assert [e.payload["ok"] for e in ev] == [False, False, False]
