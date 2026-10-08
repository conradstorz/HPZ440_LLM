import json

import httpx
import pytest

from obiwan import cli


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization"),
                     json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(cli, "_transport", lambda: httpx.MockTransport(handler))
    monkeypatch.setenv("OBIWAN_READER_TOKEN", "r")
    monkeypatch.setenv("OBIWAN_WRITER_TOKEN", "w")
    monkeypatch.setenv("OBIWAN_COMMANDER_TOKEN", "c")
    monkeypatch.setenv("OBIWAN_BASE_URL", "http://obiwan.test:8070")
    return seen


def test_each_command_uses_the_least_credential_it_needs(calls, capsys):
    assert cli.main(["scan"]) == 0
    assert cli.main(["reindex"]) == 0
    assert cli.main(["status"]) == 0
    assert cli.main(["confirm", "abc"]) == 0
    assert cli.main(["forget", "abc", "--reason", "wrong"]) == 0
    assert calls == [
        ("POST", "/scan", "Bearer w", None),
        ("POST", "/reindex", "Bearer w", None),
        ("GET", "/status", "Bearer r", None),
        ("POST", "/confirm", "Bearer c", {"subject_id": "abc", "action": "promote"}),
        ("POST", "/confirm", "Bearer c", {"subject_id": "abc", "action": "forget", "reason": "wrong"}),
    ]
    assert capsys.readouterr().out.count('"ok": true') == 5


def test_forget_requires_a_reason(calls):
    with pytest.raises(SystemExit):
        cli.main(["forget", "abc"])


def test_a_refusal_is_reported_not_swallowed(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_transport", lambda: httpx.MockTransport(lambda r: httpx.Response(403, json={"detail": "nope"})))
    monkeypatch.setenv("OBIWAN_COMMANDER_TOKEN", "c")
    assert cli.main(["confirm", "abc"]) == 1
    assert "403" in capsys.readouterr().err
