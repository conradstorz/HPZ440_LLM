import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.core.nko import KnowledgeType, NKOStatus, sender_address
from jarvis.sources.gmail import SCOPES, AuthRequired, GmailSource, GoogleGmailAPI, attachment_parts, normalize
from tests.conftest import FIXTURES, load_fixture


class FakeAPI:
    def __init__(self):
        self.plain = load_fixture("gmail_message_plain.json")
        self.html = load_fixture("gmail_message_html_with_attachment.json")
        self.calls = []

    def list_ids(self, query):
        self.calls.append(("list", query))
        return [self.plain["id"], self.html["id"]]

    def get_full(self, mid):
        return self.plain if mid == self.plain["id"] else self.html

    def get_raw(self, mid):
        name = "gmail_raw_plain.eml" if mid == self.plain["id"] else "gmail_raw_html.eml"
        return (FIXTURES / name).read_bytes()

    def get_attachment(self, mid, attachment_id):
        return (FIXTURES / f"gmail_attachment_{attachment_id}.bin").read_bytes()


def test_scope_is_read_only():
    assert SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_normalize_plain():
    raw = (FIXTURES / "gmail_raw_plain.eml").read_bytes()
    n = normalize(load_fixture("gmail_message_plain.json"), raw, account="conradstorz@gmail.com", attachments=[])
    assert n.knowledge_type == KnowledgeType.EMAIL and n.status == NKOStatus.CAPTURED and n.version == 0
    assert n.dedup_key == "gmail:conradstorz@gmail.com:18f1a2b3c4d5e6f7"
    assert n.source_identifier == "18f1a2b3c4d5e6f7" and n.source_account == "conradstorz@gmail.com"
    assert n.subject == "Invoice approval needed"
    assert sender_address(n) == "alice@example.com"
    assert n.participants[0] == {"role": "from", "name": "Alice Example", "address": "alice@example.com"}
    assert any(p["role"] == "to" and p["address"] == "conradstorz@gmail.com" for p in n.participants)
    assert "approve the invoice by Friday" in n.content
    assert n.received_at == datetime(2025, 9, 30, 0, 0, tzinfo=UTC)
    assert n.occurred_at == datetime(2025, 9, 29, 20, 0, tzinfo=UTC)
    assert n.references[0] == {"thread_id": "18f1a2b3c4d5e6f7", "message_id_header": "<abc123@example.com>", "in_reply_to": None}
    assert n.facts[0] == {"kind": "raw_sha256", "value": hashlib.sha256(raw).hexdigest()}
    assert n.raw_metadata["snippet"] == "Can you approve the invoice by Friday?"
    assert "data" not in str(n.raw_metadata["payload"])


def test_normalize_html_strips_tags_and_lists_attachment():
    p = load_fixture("gmail_message_html_with_attachment.json")
    parts = attachment_parts(p)
    assert parts == [{"filename": "statement.pdf", "mime": "application/pdf", "size": 11, "attachment_id": "ATT-1"}]
    n = normalize(p, b"raw", account="a@b", attachments=[{"filename": "statement.pdf", "mime": "application/pdf", "size": 11, "sha256": "x", "path": "attachments/x-statement.pdf"}])
    assert "<b>" not in n.content and "September statement" in n.content
    assert n.attachments[0]["sha256"] == "x"
    assert n.references[0]["in_reply_to"] == "<stmt-0831@utility.example>"


def test_poll_stores_raw_and_attachments_and_skips_existing(data_dir, store):
    api = FakeAPI()
    src = GmailSource(api, store, account="conradstorz@gmail.com", query="in:inbox", max_attachment_bytes=25_000_000)
    since = datetime(2025, 9, 20, tzinfo=UTC)
    got = list(src.poll(since))
    assert [n.source_identifier for n in got] == ["18f1a2b3c4d5e6f7", "18f1a2b3c4d5e6f8"]
    # One day earlier than ``since``: Gmail's after: is day-granular and account-timezone-based, so a
    # UTC-floored date can cut inside the window the caller asked for. See GmailSource.poll.
    assert api.calls[0] == ("list", "in:inbox after:2025/09/19")
    d = data_dir / "archive" / "gmail_conradstorz@gmail.com_18f1a2b3c4d5e6f8"
    assert (d / "raw.eml").exists()
    att = got[1].attachments[0]
    assert att["sha256"] == hashlib.sha256(b"%PDF-1.4 x\n").hexdigest()
    assert (d / att["path"]).read_bytes() == b"%PDF-1.4 x\n"
    assert not store.exists(got[0].dedup_key), "poll yields v0 but does not save it; the pipeline saves"
    store.save_version(got[0])
    assert [n.source_identifier for n in src.poll(since)] == ["18f1a2b3c4d5e6f8"]


def test_poll_window_is_never_narrower_than_the_caller_asked_for(data_dir, store):
    """Just after midnight UTC, the date floor must not swallow the previous day.

    ``since`` 00:30 on the 21st means "everything from 00:30 on the 21st". Gmail can only filter by
    date, in the account's own timezone, so ``after:2025/09/21`` would drop every message from the
    20th -- including the evening mail a caller polling hourly still needs. Naming the 20th keeps the
    clause a lower bound; ``query`` is where a tighter window belongs, and dedup absorbs the overlap.
    """
    api = FakeAPI()
    src = GmailSource(api, store, account="a", query="in:inbox newer_than:1d", max_attachment_bytes=25_000_000)
    list(src.poll(datetime(2025, 9, 21, 0, 30, tzinfo=UTC)))
    assert api.calls[0] == ("list", "in:inbox newer_than:1d after:2025/09/20")


def test_poll_skips_oversized_attachment(data_dir, store):
    src = GmailSource(FakeAPI(), store, account="a", query="q", max_attachment_bytes=5)
    got = [n for n in src.poll(datetime(2025, 9, 20, tzinfo=UTC)) if n.attachments]
    att = got[0].attachments[0]
    assert att["path"] is None and att["skipped_reason"] == "too_large" and "sha256" not in att


def test_missing_token_raises_auth_required(tmp_path: Path):
    with pytest.raises(AuthRequired) as e:
        GoogleGmailAPI(tmp_path / "token.json")
    assert "jarvis-auth.ps1" in str(e.value)


def test_token_with_extra_scope_is_refused(tmp_path: Path):
    import json
    token = tmp_path / "token.json"
    token.write_text(json.dumps({
        "token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.modify"],
    }), encoding="utf-8")
    with pytest.raises(AuthRequired) as e:
        GoogleGmailAPI(token)
    assert "requires exactly" in str(e.value) and "jarvis-auth.ps1" in str(e.value)


def test_token_with_missing_scope_is_refused(tmp_path: Path):
    import json
    token = tmp_path / "token.json"
    token.write_text(json.dumps({
        "token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s",
        "token_uri": "https://oauth2.googleapis.com/token", "scopes": [],
    }), encoding="utf-8")
    with pytest.raises(AuthRequired) as e:
        GoogleGmailAPI(token)
    assert "requires exactly" in str(e.value)


def test_empty_account_is_refused(store):
    with pytest.raises(ValueError) as e:
        GmailSource(FakeAPI(), store, account="", query="in:inbox", max_attachment_bytes=1)
    assert "JARVIS_GMAIL_ACCOUNT" in str(e.value)


def test_unreadable_token_is_auth_required(tmp_path: Path):
    token = tmp_path / "token.json"
    token.write_text("{not json", encoding="utf-8")
    with pytest.raises(AuthRequired):
        GoogleGmailAPI(token)


def test_consent_flow_rejects_empty_and_invalid_credentials(tmp_path: Path):
    from jarvis.sources.gmail import run_consent_flow

    empty = tmp_path / "credentials.json"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="is empty"):
        run_consent_flow(empty, tmp_path / "token.json")
    empty.write_text("\ufeff{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        run_consent_flow(empty, tmp_path / "token.json")


def _http_error(status: int, reason: str):
    import httplib2
    from googleapiclient.errors import HttpError

    content = json.dumps({"error": {"code": status, "message": f"Quota exceeded ({reason})",
                                    "errors": [{"domain": "usageLimits", "reason": reason,
                                                "message": f"Quota exceeded ({reason})"}]}}).encode("utf-8")
    return HttpError(httplib2.Response({"status": status}), content, uri="https://gmail.example/messages")


class FlakyRequest:
    """Stands in for a googleapiclient request: raises the queued errors, then returns the payload."""

    def __init__(self, errors, result):
        self._errors, self._result, self.attempts = list(errors), result, 0

    def execute(self):
        self.attempts += 1
        if self._errors:
            raise self._errors.pop(0)
        return self._result


def test_execute_backs_off_on_rate_limit_then_succeeds(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr("jarvis.sources.gmail._sleep", delays.append)
    req = FlakyRequest([_http_error(403, "rateLimitExceeded")] * 2, {"ok": 1})
    assert GoogleGmailAPI._execute(req) == {"ok": 1}
    assert delays == [2, 4] and req.attempts == 3


def test_execute_gives_up_after_the_whole_schedule(monkeypatch):
    from googleapiclient.errors import HttpError

    delays: list[float] = []
    monkeypatch.setattr("jarvis.sources.gmail._sleep", delays.append)
    req = FlakyRequest([_http_error(429, "userRateLimitExceeded")] * 20, None)
    with pytest.raises(HttpError):
        GoogleGmailAPI._execute(req)
    assert delays == [2, 4, 8, 16, 32, 60] and req.attempts == 7


def test_execute_retries_a_429_with_no_reason_in_the_body(monkeypatch):
    """A 429 from a proxy carries no Google reason; it is still a rate limit and must back off."""
    import httplib2
    from googleapiclient.errors import HttpError

    delays: list[float] = []
    monkeypatch.setattr("jarvis.sources.gmail._sleep", delays.append)
    bare = HttpError(httplib2.Response({"status": 429}), b"<html>429 Too Many Requests</html>",
                     uri="https://gmail.example/messages")
    req = FlakyRequest([bare], {"ok": 1})
    assert GoogleGmailAPI._execute(req) == {"ok": 1}
    assert delays == [2] and req.attempts == 2


def test_execute_does_not_retry_a_403_for_another_reason(monkeypatch):
    from googleapiclient.errors import HttpError

    delays: list[float] = []
    monkeypatch.setattr("jarvis.sources.gmail._sleep", delays.append)
    req = FlakyRequest([_http_error(403, "insufficientPermissions")], {"ok": 1})
    with pytest.raises(HttpError):
        GoogleGmailAPI._execute(req)
    assert delays == [] and req.attempts == 1


def test_execute_retries_a_server_error(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr("jarvis.sources.gmail._sleep", delays.append)
    req = FlakyRequest([_http_error(503, "backendError")], {"ok": 1})
    assert GoogleGmailAPI._execute(req) == {"ok": 1}
    assert delays == [2]


def test_poll_stops_paging_when_the_consumer_stops(data_dir, store):
    """list_ids is a generator: taking one id must not cost the second page."""
    pages = []

    class PagedAPI(FakeAPI):
        def list_ids(self, query):
            pages.append(1)
            yield self.plain["id"]
            pages.append(2)
            yield self.html["id"]

    src = GmailSource(PagedAPI(), store, account="a", query="q", max_attachment_bytes=25_000_000)
    it = src.poll(datetime(2025, 9, 20, tzinfo=UTC))
    next(it)
    assert pages == [1]
    it.close()
