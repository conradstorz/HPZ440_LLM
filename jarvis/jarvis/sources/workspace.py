"""Client for GTE's passive workspace agent: list files, fetch bytes, extract text. Jarvis initiates; the agent never calls up."""

from __future__ import annotations

import io
import threading
from pathlib import Path

import httpx

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml", ".toml", ".ini"}
# A document the agent can neither hold in context nor usefully summarise is not worth the memory it would take.
MAX_DOCUMENT_BYTES = 5_000_000
MAX_PDF_PAGES = 20


class WorkspaceUnavailable(Exception):
    pass


def extract_text(name: str, data: bytes, *, max_pdf_pages: int = MAX_PDF_PAGES) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return data.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            pages = reader.pages[:max_pdf_pages] if max_pdf_pages > 0 else reader.pages
            return "\n".join((page.extract_text() or "") for page in pages)
        except Exception as e:  # noqa: BLE001 - a broken PDF is not a reason to fail the tool
            return f"(could not extract PDF text: {type(e).__name__})"
    return None


class WorkspaceClient:
    def __init__(self, base_url: str, token_path: Path, *, timeout: float = 30.0, transport: httpx.BaseTransport | None = None,
                 max_document_bytes: int = MAX_DOCUMENT_BYTES, max_pdf_pages: int = MAX_PDF_PAGES) -> None:
        self.base_url = base_url.rstrip("/")
        self._token_path = Path(token_path)
        self._max_document_bytes = max_document_bytes
        self._max_pdf_pages = max_pdf_pages
        self._client = httpx.Client(timeout=timeout, transport=transport)
        # Per request thread: sha256 -> every file in that thread's last listing with that content; identical files
        # under different names share one sha and must not overwrite each other. One client serves every concurrent
        # chat, so a listing in one thread must never authorise a read in another.
        self._tls = threading.local()

    def _headers(self) -> dict[str, str]:
        if not self.base_url:
            raise WorkspaceUnavailable("no workspace agent configured (JARVIS_WORKSPACE_AGENT_URL is empty)")
        try:
            token = self._token_path.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise WorkspaceUnavailable(f"agent_token not readable at {self._token_path} ({type(e).__name__})") from e
        if not token:
            raise WorkspaceUnavailable(f"agent_token at {self._token_path} is empty")
        return {"Authorization": f"Bearer {token}"}

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            resp = self._client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kw)
        except httpx.HTTPError as e:
            raise WorkspaceUnavailable(f"workspace agent unreachable: {type(e).__name__}") from e
        if resp.status_code == 401:
            raise WorkspaceUnavailable("workspace agent rejected the token (HTTP 401); re-pair with scripts/jarvis-agent-token.ps1")
        if resp.status_code >= 400:
            raise WorkspaceUnavailable(f"workspace agent returned HTTP {resp.status_code}")
        return resp

    def list_documents(self, glob: str = "*") -> list[dict]:
        matches = self._request("POST", "/scan", json={"patterns": [{"glob": glob}]}).json().get("matches", [])
        docs = [{"name": m.get("name") or m.get("path", ""), "folder": m.get("folder", ""), "size": m.get("size", 0),
                 "mtime": m.get("mtime", ""), "sha256": m.get("sha256", "")} for m in matches]
        last: dict[str, list[dict]] = {}
        for d in docs:
            if d["sha256"]:
                last.setdefault(d["sha256"], []).append(d)
        self._tls.last = last
        return docs

    def read_document(self, sha256: str) -> tuple[dict, str | None]:
        # No implicit whole-workstation scan: a read is only ever for something a listing already showed.
        last = getattr(self._tls, "last", None)
        if not last:
            raise KeyError("call list_documents first")
        matches = [ds for k, ds in last.items() if k.startswith(sha256)]
        if len(matches) != 1:
            raise KeyError(f"{sha256}: {'no' if not matches else 'ambiguous'} match in the last listing; call list_documents first")
        meta = matches[0][0]
        try:
            size = int(meta.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > self._max_document_bytes:
            # The listing already told us the size, so refuse before the download rather than after it.
            return {**meta, "skipped_reason": "too_large"}, None
        data = self._request("GET", f"/file/{meta['sha256']}").content
        return meta, extract_text(meta["name"], data, max_pdf_pages=self._max_pdf_pages)
