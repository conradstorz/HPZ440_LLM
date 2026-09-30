import pytest

from jarvis.agent import PERSONA, Agent
from jarvis.core.llm import ChatTurn, FakeLLM, LLMError, ToolCall
from jarvis.journal import Journal
from jarvis.notes import Notes
from jarvis.policy import Policy
from jarvis.tools import Tool, ToolRegistry


def _tools(data_dir):
    j = Journal(data_dir)
    reg = ToolRegistry(Policy(j), j, [Tool(name="lookup", description="d", action="read", handler=lambda q: f"result for {q}",
                                            parameters={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]})])
    return reg, j


def _agent(data_dir, llm, **kw):
    reg, j = _tools(data_dir)
    return Agent(llm, reg, Notes(data_dir, j), j, **kw), j


def test_persona_and_notes_in_system_prompt(data_dir):
    llm = FakeLLM(turns=[ChatTurn(content="hi")])
    agent, j = _agent(data_dir, llm)
    Notes(data_dir, j).propose("Always be brief.", "chat", "explicit")
    out = "".join(agent.respond([{"role": "user", "content": "hello"}]))
    assert out == "hi"
    system = llm.chat_calls[0]["messages"][0]
    assert system["role"] == "system" and PERSONA.split("\n")[0] in system["content"]
    assert "untrusted data" in system["content"] and "1. Always be brief." in system["content"]
    assert llm.chat_calls[0]["tools"][0]["function"]["name"] == "lookup"


def test_one_tool_call_then_answer(data_dir):
    llm = FakeLLM(turns=[ChatTurn(content="", tool_calls=[ToolCall(id="c1", name="lookup", arguments={"q": "bill"})], finish_reason="tool_calls"),
                         ChatTurn(content="The bill is 42.")])
    agent, j = _agent(data_dir, llm)
    out = "".join(agent.respond([{"role": "user", "content": "what is the bill?"}], conversation_id="conv"))
    assert out == "The bill is 42."
    second = llm.chat_calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "name": "lookup", "content": "result for bill"}
    ev = [e for e in j.iter_all()]
    assert [e.kind for e in ev] == ["tool_call", "chat"]
    assert ev[-1].payload["steps"] == 1 and ev[-1].payload["tools_used"] == ["lookup"] and ev[-1].payload["conversation_id"] == "conv"


def test_step_limit_then_forced_answer(data_dir):
    call = ChatTurn(content="", tool_calls=[ToolCall(id="c", name="lookup", arguments={"q": "x"})], finish_reason="tool_calls")
    llm = FakeLLM(turns=[call, call, call], stream_chunks=["best ", "effort"])
    agent, j = _agent(data_dir, llm, max_steps=2)
    out = "".join(agent.respond([{"role": "user", "content": "loop"}]))
    assert out == "best effort"
    assert len(llm.chat_calls) == 4 and llm.chat_calls[3].get("stream") is True
    assert "answer now" in llm.chat_calls[3]["messages"][-1]["content"].lower()
    chat = [e for e in j.iter_all() if e.kind == "chat"][0]
    assert chat.payload["steps_exhausted"] is True and chat.payload["steps"] == 2


def test_unknown_tool_is_rejected_and_loop_continues(data_dir):
    llm = FakeLLM(turns=[ChatTurn(content="", tool_calls=[ToolCall(id="c", name="send_mail", arguments={})], finish_reason="tool_calls"),
                         ChatTurn(content="I cannot send mail.")])
    agent, j = _agent(data_dir, llm)
    assert "".join(agent.respond([{"role": "user", "content": "send it"}])) == "I cannot send mail."
    assert llm.chat_calls[1]["messages"][-1]["content"].startswith("error: unknown tool")
    assert [e.kind for e in j.iter_all()][0] == "policy_reject"


def test_transcript_trimming_keeps_system_and_last_user(data_dir):
    llm = FakeLLM(turns=[ChatTurn(content="ok")])
    agent, _ = _agent(data_dir, llm, context_tokens=600, reply_tokens=100)
    msgs = [{"role": "user", "content": "old " * 300}, {"role": "assistant", "content": "older reply " * 100},
            {"role": "user", "content": "the real question"}]
    "".join(agent.respond(msgs))
    sent = llm.chat_calls[0]["messages"]
    assert sent[0]["role"] == "system" and sent[-1]["content"] == "the real question"
    assert not any(m.get("content", "").startswith("old ") for m in sent)


def test_llm_down_gives_friendly_reply(data_dir):
    llm = FakeLLM(turns=[LLMError("connection refused")])
    agent, j = _agent(data_dir, llm)
    out = "".join(agent.respond([{"role": "user", "content": "hi"}]))
    assert out.startswith("I can't reach the local model right now")
    assert [e.kind for e in j.iter_all()] == ["error", "chat"]


def test_pending_note_confirmation_hint(data_dir):
    llm = FakeLLM(turns=[ChatTurn(content="saved")])
    agent, j = _agent(data_dir, llm)
    n = Notes(data_dir, j).propose("Bob likes brevity.", "draft", "proposed")
    msgs = [{"role": "user", "content": "bob likes short mails"},
            {"role": "assistant", "content": f"Noted as pending note {n.id}. Save this note? (yes/no)"},
            {"role": "user", "content": "yes"}]
    "".join(agent.respond(msgs))
    sent = llm.chat_calls[0]["messages"]
    assert sent[-1]["role"] == "system" and n.id in sent[-1]["content"] and "confirm_note" in sent[-1]["content"]


def test_multimodal_content_parts_are_flattened(data_dir):
    llm = FakeLLM(turns=[ChatTurn(content="ok")])
    agent, _ = _agent(data_dir, llm)
    "".join(agent.respond([{"role": "user", "content": [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]}]))
    assert llm.chat_calls[0]["messages"][-1]["content"] == "part one\npart two"
