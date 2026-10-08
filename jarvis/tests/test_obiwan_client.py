import json

import httpx
import pytest

from jarvis.obiwan_client import ObiwanClient, ObiwanUnavailable


def _client(handler, base="http://obiwan:8070"):
    return ObiwanClient(base, reader_token="r", writer_token="w", transport=httpx.MockTransport(handler))


def test_each_call_uses_the_least_credential_and_never_names_an_origin():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        seen.append((req.method, req.url.path, dict(req.url.params), req.headers["authorization"], body))
        return httpx.Response(200, json={"ok": True})

    c = _client(handler)
    c.search("zebras", k=3)
    c.submit("a guess", title="t")
    c.relay("a fact", "chat-9")
    c.status()
    assert seen == [
        ("GET", "/search", {"q": "zebras", "k": "3"}, "Bearer r", None),
        ("POST", "/submit", {}, "Bearer w", {"content": "a guess", "title": "t"}),
        ("POST", "/relay", {}, "Bearer w", {"content": "a fact", "conversation_ref": "chat-9", "title": None}),
        ("GET", "/status", {}, "Bearer r", None),
    ]
    for call in seen:
        assert not call[4] or not ({"origin", "attestation"} & set(call[4]))


def test_the_client_has_no_commander_credential():
    c = _client(lambda r: httpx.Response(200, json={}))
    assert not any("commander" in k.lower() for k in vars(c)) and not hasattr(c, "confirm") and not hasattr(c, "forget")


@pytest.mark.parametrize("status, text", [(401, "unknown credential"), (403, "does not hold"), (500, "boom")])
def test_http_errors_become_obiwan_unavailable_with_the_status(status, text):
    c = _client(lambda r: httpx.Response(status, json={"detail": text}))
    with pytest.raises(ObiwanUnavailable, match=str(status)):
        c.search("x")


def test_transport_errors_and_an_unconfigured_url_are_obiwan_unavailable():
    def boom(_):
        raise httpx.ConnectError("refused")

    with pytest.raises(ObiwanUnavailable, match="unreachable"):
        _client(boom).status()
    with pytest.raises(ObiwanUnavailable, match="JARVIS_OBIWAN_URL"):
        _client(lambda r: httpx.Response(200, json={}), base="").status()
