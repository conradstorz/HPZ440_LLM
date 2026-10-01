import json

import httpx
import pytest

from jarvis.core.llm import ChatTurn, FakeLLM, LlamaCppClient, LLMError, ToolCall


def _transport(handler):
    return httpx.MockTransport(handler)


def test_llama_client_parses_json_content():
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        assert body["response_format"]["type"] == "json_schema"
        assert req.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"group": "fyi"}'}}]})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    assert c.complete_json("s", "u", {"type": "object"}) == {"group": "fyi"}


def test_llama_client_raises_llm_error_on_bad_json():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    with pytest.raises(LLMError):
        c.complete_json("s", "u", {})


def test_llama_client_raises_llm_error_on_null_content():
    """A 200 with content: null must be an LLMError, not a TypeError escaping the client."""
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    with pytest.raises(LLMError):
        c.complete_json("s", "u", {})


def test_llama_client_raises_llm_error_on_a_non_mapping_choice():
    def handler(req):
        return httpx.Response(200, json={"choices": ["nonsense"]})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    with pytest.raises(LLMError):
        c.complete_json("s", "u", {})


def test_llama_client_raises_on_http_error():
    c = LlamaCppClient("http://llm", "m", transport=_transport(lambda r: httpx.Response(500)))
    with pytest.raises(LLMError):
        c.complete_json("s", "u", {})


def test_llama_client_http_status_error_includes_response_body():
    def handler(req):
        return httpx.Response(400, json={"error": {"message": "prompt too long"}})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    with pytest.raises(LLMError) as exc_info:
        c.complete_json("s", "u", {})
    assert "HTTP 400" in str(exc_info.value)
    assert "prompt too long" in str(exc_info.value)


def test_llama_client_raises_on_truncated_output():
    def handler(req):
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"group": "fyi"'}}]}
        )
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    with pytest.raises(LLMError) as exc_info:
        c.complete_json("s", "u", {})
    assert "truncated" in str(exc_info.value)


def test_fake_llm_queue():
    f = FakeLLM([{"a": 1}, LLMError("x")])
    assert f.complete_json("s", "u", {}) == {"a": 1}
    with pytest.raises(LLMError):
        f.complete_json("s", "u", {})
    assert len(f.calls) == 2


def test_chat_parses_tool_calls():
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        assert body["tools"][0]["function"]["name"] == "search_mail" and body["tool_choice"] == "auto"
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search_mail", "arguments": "{\"query\": \"bill\"}"}},
                           {"type": "function", "function": {"name": "x", "arguments": "not json"}}]}}]})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    turn = c.chat([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "search_mail", "parameters": {}}}])
    assert turn.finish_reason == "tool_calls" and turn.content == ""
    assert turn.tool_calls[0] == ToolCall(id="c1", name="search_mail", arguments={"query": "bill"})
    assert turn.tool_calls[1].arguments == {"_raw": "not json"} and turn.tool_calls[1].id.startswith("call_")


def test_chat_without_tools_omits_tools_key():
    def handler(req):
        assert "tools" not in json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "hello"}}]})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    assert c.chat([{"role": "user", "content": "hi"}]) == ChatTurn(content="hello", tool_calls=[], finish_reason="stop")


def test_chat_stream_yields_deltas():
    sse = ('data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
           'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
           'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
           'data: [DONE]\n\n')
    def handler(req):
        assert json.loads(req.content)["stream"] is True
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
    c = LlamaCppClient("http://llm", "m", transport=_transport(handler))
    assert list(c.chat_stream([{"role": "user", "content": "hi"}])) == ["Hel", "lo"]


def test_chat_http_error_is_llm_error():
    c = LlamaCppClient("http://llm", "m", transport=_transport(lambda r: httpx.Response(503, text="down")))
    with pytest.raises(LLMError, match="HTTP 503"):
        c.chat([{"role": "user", "content": "hi"}])
    with pytest.raises(LLMError):
        list(c.chat_stream([{"role": "user", "content": "hi"}]))


def test_fake_llm_chat_and_stream():
    f = FakeLLM(turns=[ChatTurn(content=None, tool_calls=[ToolCall(id="1", name="t", arguments={})], finish_reason="tool_calls"),
                       ChatTurn(content="done")], stream_chunks=["a", "b"])
    assert f.chat([{"role": "user", "content": "x"}], [{"type": "function"}]).tool_calls[0].name == "t"
    assert f.chat([]).content == "done"
    assert list(f.chat_stream([])) == ["a", "b"]
    assert f.chat_calls[0]["tools"] == [{"type": "function"}]
    with pytest.raises(LLMError):
        f.chat([])


def test_per_request_timeout_overrides_the_client_default():
    """The agent's remaining deadline has to bound the blocking read, not just the gap between steps."""
    seen: list = []

    def handler(req: httpx.Request):
        seen.append(req.extensions.get("timeout"))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}]})

    c = LlamaCppClient("http://llm", "m", timeout=120.0, transport=_transport(handler))
    c.chat([{"role": "user", "content": "hi"}], timeout=7.0)
    c.chat([{"role": "user", "content": "hi"}])
    assert seen[0]["read"] == 7.0
    assert seen[1]["read"] == 120.0  # omitted means keep the client default, not "wait forever"
