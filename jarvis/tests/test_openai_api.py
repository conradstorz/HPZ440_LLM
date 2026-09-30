import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis.openai_api import openai_router


def _app(respond):
    app = FastAPI()
    app.include_router(openai_router(respond))
    return TestClient(app)


def test_models():
    c = _app(lambda m, cid: iter(["x"]))
    r = c.get("/v1/models")
    assert r.status_code == 200 and r.json()["data"][0]["id"] == "jarvis"


def test_non_stream_response_shape():
    seen = {}

    def respond(messages, conversation_id):
        seen["messages"], seen["cid"] = messages, conversation_id
        yield "Hel"
        yield "lo"

    c = _app(respond)
    r = c.post("/v1/chat/completions", json={"model": "jarvis", "messages": [{"role": "user", "content": "hi"}], "chat_id": "abc"})
    body = r.json()
    assert r.status_code == 200 and body["object"] == "chat.completion" and body["model"] == "jarvis"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "Hello"} and body["choices"][0]["finish_reason"] == "stop"
    assert seen["messages"] == [{"role": "user", "content": "hi"}] and seen["cid"] == "abc"


def test_stream_sse():
    c = _app(lambda m, cid: iter(["Hel", "lo"]))
    with c.stream("POST", "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
                  headers={"x-openwebui-chat-id": "h1"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        lines = [ln for ln in r.iter_lines() if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(ln[6:]) for ln in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"].get("role") == "assistant"
    assert "".join(ch["choices"][0]["delta"].get("content", "") for ch in chunks) == "Hello"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop" and all(ch["object"] == "chat.completion.chunk" for ch in chunks)


def test_conversation_id_from_header_when_body_lacks_it():
    seen = {}

    def respond(messages, conversation_id):
        seen["cid"] = conversation_id
        yield "x"

    c = _app(respond)
    c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}, headers={"x-openwebui-chat-id": "h1"})
    assert seen["cid"] == "h1"


def test_malformed_body_is_400_and_responder_error_is_not_500():
    c = _app(lambda m, cid: iter(["x"]))
    assert c.post("/v1/chat/completions", json={"messages": "nope"}).status_code == 400
    assert c.post("/v1/chat/completions", json={"messages": [{"role": "user"}]}).status_code == 400

    def bad(messages, conversation_id):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    c2 = _app(bad)
    r = c2.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200 and "boom" in r.json()["choices"][0]["message"]["content"]
