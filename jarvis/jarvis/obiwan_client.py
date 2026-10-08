"""Client for Obi-Wan, the Historian. Jarvis holds the reader and writer credentials and nothing else (A3, A4, A5, D4)."""

from __future__ import annotations

import httpx


class ObiwanUnavailable(Exception):
    pass


class ObiwanClient:
    def __init__(self, base_url: str, *, reader_token: str, writer_token: str, timeout: float = 30.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._reader, self._writer = reader_token, writer_token
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _request(self, method: str, path: str, *, token: str, **kw) -> dict:
        if not self.base_url:
            raise ObiwanUnavailable("no knowledge store configured (JARVIS_OBIWAN_URL is empty)")
        try:
            resp = self._client.request(method, f"{self.base_url}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)
        except httpx.HTTPError as e:
            raise ObiwanUnavailable(f"Obi-Wan unreachable: {type(e).__name__}") from e
        if resp.status_code >= 400:
            detail = resp.text[:200]
            raise ObiwanUnavailable(f"Obi-Wan returned HTTP {resp.status_code}: {detail}")
        return resp.json()

    def search(self, query: str, k: int = 8) -> dict:
        return self._request("GET", "/search", token=self._reader, params={"q": query, "k": k})

    def submit(self, content: str, title: str | None = None) -> dict:
        return self._request("POST", "/submit", token=self._writer, json={"content": content, "title": title})

    def relay(self, content: str, conversation_ref: str, title: str | None = None) -> dict:
        return self._request("POST", "/relay", token=self._writer, json={"content": content, "conversation_ref": conversation_ref, "title": title})

    def status(self) -> dict:
        return self._request("GET", "/status", token=self._reader)
