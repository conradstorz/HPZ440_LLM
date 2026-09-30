import json

import httpx
import pytest

from jarvis.core.llm import FakeLLM, LlamaCppClient, LLMError


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
