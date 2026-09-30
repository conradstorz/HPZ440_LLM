"""Gmail source: read-only scope, yields v0 NKOs. The Google API is behind a small protocol so tests never touch it."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

from jarvis.core.nko import NKO, KnowledgeType, NKOStatus
from jarvis.core.store import Store
from jarvis.sources.htmltext import html_to_text

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

logger = logging.getLogger(__name__)
# Indirection so tests can replace the sleep without waiting out the real schedule.
_sleep = time.sleep
# Google's per-user "Units per minute" quota refills on a one-minute window, so the last wait covers a whole window.
BACKOFF_SECONDS = (2, 4, 8, 16, 32, 60)
RETRYABLE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})


class AuthRequired(Exception):
    pass


def _error_reasons(e: Any) -> set[str]:
    """Every ``reason`` Google put in the error, from error_details and from the raw JSON body."""
    out: set[str] = set()

    def collect(items: Any) -> None:
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("reason"), str):
                    out.add(item["reason"])

    collect(getattr(e, "error_details", None))  # a str when Google sent only a message; collect() ignores it
    content = getattr(e, "content", None)
    if isinstance(content, bytes | bytearray):
        try:
            content = bytes(content).decode("utf-8")
        except UnicodeDecodeError:
            content = None
    if isinstance(content, str):
        try:
            body = json.loads(content)
        except ValueError:
            body = None
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            collect(err.get("errors"))
            collect(err.get("details"))
    return out


def _is_retryable(e: Any) -> bool:
    status = int(getattr(getattr(e, "resp", None), "status", 0) or 0)
    if 500 <= status < 600:
        return True
    return status in (403, 429) and bool(_error_reasons(e) & RETRYABLE_REASONS)


class GmailAPI(Protocol):
    def list_ids(self, query: str) -> Iterator[str]: ...
    def get_full(self, mid: str) -> dict: ...
    def get_raw(self, mid: str) -> bytes: ...
    def get_attachment(self, mid: str, attachment_id: str) -> bytes: ...


class GoogleGmailAPI:
    def __init__(self, token_path: Path) -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not Path(token_path).exists():
            raise AuthRequired(f"{token_path} not found. Run scripts/jarvis-auth.ps1 on the workstation first.")
        try:
            info = json.loads(Path(token_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise AuthRequired(f"{token_path} is unreadable ({e}). Run scripts/jarvis-auth.ps1 again.") from e
        granted = set(info.get("scopes") or [])
        if granted != set(SCOPES):
            raise AuthRequired(f"{token_path} scopes are {sorted(granted)}; Jarvis requires exactly {SCOPES}. Delete it and run scripts/jarvis-auth.ps1 again.")
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:  # noqa: BLE001
                    raise AuthRequired(f"Gmail token refresh failed ({e}). Run scripts/jarvis-auth.ps1 again.") from e
            else:
                raise AuthRequired("Gmail token is invalid and cannot be refreshed. Run scripts/jarvis-auth.ps1 again.")
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)

    @staticmethod
    def _execute(request: Any) -> Any:
        """Run one Google API request, backing off on rate limits and 5xx. Any other error is raised at once."""
        from googleapiclient.errors import HttpError

        for delay in BACKOFF_SECONDS:
            try:
                return request.execute()
            except HttpError as e:
                if not _is_retryable(e):
                    raise
                logger.warning("Gmail API %s (%s); retrying in %ss",
                               getattr(getattr(e, "resp", None), "status", "?"), sorted(_error_reasons(e)), delay)
                _sleep(delay)
        return request.execute()  # the schedule is spent; let this one's error reach the caller

    def list_ids(self, query: str) -> Iterator[str]:
        """Yield ids page by page so a consumer that stops early never pays for the next page."""
        token = None
        while True:
            resp = self._execute(self._svc.users().messages().list(userId="me", q=query, pageToken=token, maxResults=100))
            for m in resp.get("messages", []):
                yield m["id"]
            token = resp.get("nextPageToken")
            if not token:
                return

    def get_full(self, mid: str) -> dict:
        return self._execute(self._svc.users().messages().get(userId="me", id=mid, format="full"))

    def get_raw(self, mid: str) -> bytes:
        r = self._execute(self._svc.users().messages().get(userId="me", id=mid, format="raw"))
        return _b64d(r["raw"])

    def get_attachment(self, mid: str, attachment_id: str) -> bytes:
        r = self._execute(self._svc.users().messages().attachments().get(userId="me", messageId=mid, id=attachment_id))
        return _b64d(r["data"])


def run_consent_flow(credentials_path: Path, token_path: Path) -> str:
    """One-time OAuth consent on a machine with a browser. Writes token.json. Returns granted scopes."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    # utf-8-sig tolerates a BOM from Notepad; a clear error beats a JSONDecodeError at char 0.
    text = Path(credentials_path).read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(f"{credentials_path} is empty. Download the OAuth client JSON from Google Cloud Console and save it there.")
    try:
        client_config = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{credentials_path} is not valid JSON ({e}). Download the OAuth client JSON from Google Cloud Console.") from e
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)
    Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    return " ".join(creds.scopes or SCOPES)


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("payload", {}).get("headers", [])}


def _walk(part: dict) -> Iterator[dict]:
    yield part
    for p in part.get("parts", []) or []:
        yield from _walk(p)


def _body_text(payload: dict) -> str:
    plain, html = [], []
    for part in _walk(payload.get("payload", {})):
        data = (part.get("body") or {}).get("data")
        if not data or part.get("filename"):
            continue
        text = _b64d(data).decode("utf-8", errors="replace")
        (plain if part.get("mimeType") == "text/plain" else html if part.get("mimeType") == "text/html" else []).append(text)
    if plain:
        return "\n".join(plain).strip()
    return html_to_text("\n".join(html))


def attachment_parts(payload: dict) -> list[dict]:
    out = []
    for part in _walk(payload.get("payload", {})):
        body = part.get("body") or {}
        if part.get("filename") and body.get("attachmentId"):
            out.append({"filename": part["filename"], "mime": part.get("mimeType", "application/octet-stream"),
                        "size": int(body.get("size", 0)), "attachment_id": body["attachmentId"]})
    return out


def _strip_data(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_data(v) for k, v in obj.items() if k != "data"}
    if isinstance(obj, list):
        return [_strip_data(v) for v in obj]
    return obj


def _participants(h: dict[str, str]) -> list[dict]:
    out = []
    for role in ("from", "to", "cc"):
        for name, addr in getaddresses([h.get(role, "")]):
            if addr:
                out.append({"role": role, "name": name, "address": addr.lower()})
    return out


def _dedup_key(account: str, mid: str) -> str:
    return f"gmail:{account}:{mid}"


def normalize(payload: dict, raw: bytes, *, account: str, attachments: list[dict]) -> NKO:
    h = _headers(payload)
    mid = payload["id"]
    received = datetime.fromtimestamp(int(payload["internalDate"]) / 1000, tz=UTC)
    try:
        occurred = parsedate_to_datetime(h["date"]) if h.get("date") else None
    except (TypeError, ValueError):
        occurred = None
    return NKO.new(
        knowledge_type=KnowledgeType.EMAIL, source_system="gmail", source_account=account, source_identifier=mid,
        source_url=f"https://mail.google.com/mail/u/0/#all/{mid}", dedup_key=_dedup_key(account, mid),
        occurred_at=occurred, received_at=received, participants=_participants(h),
        subject=h.get("subject", "") or "(no subject)", content=_body_text(payload) or None,
        attachments=attachments,
        references=[{"thread_id": payload.get("threadId"), "message_id_header": h.get("message-id"), "in_reply_to": h.get("in-reply-to")}],
        facts=[{"kind": "raw_sha256", "value": hashlib.sha256(raw).hexdigest()}],
        raw_metadata={"snippet": payload.get("snippet", ""), "label_ids": payload.get("labelIds", []),
                      "payload": _strip_data(payload.get("payload", {}))},
        status=NKOStatus.CAPTURED,
    )


class GmailSource:
    name = "gmail"

    def __init__(self, api: GmailAPI, store: Store, *, account: str, query: str, max_attachment_bytes: int) -> None:
        if not account:
            raise ValueError("JARVIS_GMAIL_ACCOUNT is empty; set it in .env before running Jarvis")
        self._api, self._store = api, store
        self._account, self._query, self._max = account, query, max_attachment_bytes

    def poll(self, since: datetime) -> Iterator[NKO]:
        query = f"{self._query} after:{since.astimezone(UTC).strftime('%Y/%m/%d')}"
        for mid in self._api.list_ids(query):
            key = _dedup_key(self._account, mid)
            if self._store.exists(key):
                continue
            payload = self._api.get_full(mid)
            raw = self._api.get_raw(mid)
            self._store.save_raw(key, "raw.eml", raw)
            atts = []
            for part in attachment_parts(payload):
                entry = {"filename": part["filename"], "mime": part["mime"], "size": part["size"]}
                if part["size"] > self._max:
                    atts.append({**entry, "path": None, "skipped_reason": "too_large"})
                    continue
                data = self._api.get_attachment(mid, part["attachment_id"])
                sha = hashlib.sha256(data).hexdigest()
                rel = f"attachments/{sha[:16]}-{_SAFE.sub('_', part['filename'])}"
                self._store.save_raw(key, rel, data)
                atts.append({**entry, "sha256": sha, "path": rel})
            yield normalize(payload, raw, account=self._account, attachments=atts)
