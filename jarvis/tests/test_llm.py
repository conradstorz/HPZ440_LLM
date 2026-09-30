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


def test_llama_client_raises_on_http_error():
    c = LlamaCppClient("http://llm", "m", transport=_transport(lambda r: httpx.Response(500)))
    with pytest.raises(LLMError):
        c.complete_json("s", "u", {})


def test_fake_llm_queue():
    f = FakeLLM([{"a": 1}, LLMError("x")])
    assert f.complete_json("s", "u", {}) == {"a": 1}
    with pytest.raises(LLMError):
        f.complete_json("s", "u", {})
    assert len(f.calls) == 2
