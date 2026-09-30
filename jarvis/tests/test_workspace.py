import json
from pathlib import Path

import httpx
import pytest

from jarvis.sources.workspace import WorkspaceClient, WorkspaceUnavailable, extract_text
from tests.conftest import FIXTURES

SHA_MD = "a" * 64
SHA_PDF = "b" * 64
SHA_BIN = "c" * 64


def _agent_transport(seen: list):
    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("authorization"), req.content))
        if req.headers.get("authorization") != "Bearer tok-123":
            return httpx.Response(401, json={"detail": "invalid or missing token"})
        if req.url.path == "/scan":
            return httpx.Response(200, json={"matches": [
                {"name": "doc_sample.md", "folder": "C:/Docs", "size": 30, "mtime": "2026-09-30T00:00:00", "sha256": SHA_MD},
                {"name": "doc_sample.pdf", "folder": "C:/Docs", "size": 500, "mtime": "2026-09-30T00:00:00", "sha256": SHA_PDF},
                {"name": "photo.jpg", "folder": "C:/Docs", "size": 5, "mtime": "2026-09-30T00:00:00", "sha256": SHA_BIN}]})
        if req.url.path.startswith("/file/"):
            sha = req.url.path.rsplit("/", 1)[1]
            data = {SHA_MD: (FIXTURES / "doc_sample.md").read_bytes(), SHA_PDF: (FIXTURES / "doc_sample.pdf").read_bytes(), SHA_BIN: b"\xff\xd8"}.get(sha)
            return httpx.Response(200, content=data) if data else httpx.Response(404)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def client(tmp_path: Path):
    tok = tmp_path / "agent_token"
    tok.write_text("tok-123\n", encoding="utf-8")
    seen: list = []
    c = WorkspaceClient("http://agent:8765", tok, transport=_agent_transport(seen))
    c.seen = seen
    return c


def test_list_documents(client):
    docs = client.list_documents("*.md")
    assert [d["name"] for d in docs] == ["doc_sample.md", "doc_sample.pdf", "photo.jpg"]
    method, path, auth, content = client.seen[0]
    assert (method, path) == ("POST", "/scan") and json.loads(content) == {"patterns": [{"glob": "*.md"}]}
    assert auth == "Bearer tok-123"


def test_read_document_by_prefix_and_types(client):
    meta, text = client.read_document(SHA_MD[:12])
    assert meta["name"] == "doc_sample.md" and "Hello from the workstation" in text
    meta, text = client.read_document(SHA_PDF)
    assert meta["name"] == "doc_sample.pdf" and isinstance(text, str)
    meta, text = client.read_document(SHA_BIN)
    assert meta["name"] == "photo.jpg" and text is None
    with pytest.raises(KeyError):
        client.read_document("d" * 12)


def test_unconfigured_and_missing_token(tmp_path: Path):
    with pytest.raises(WorkspaceUnavailable, match="JARVIS_WORKSPACE_AGENT_URL"):
        WorkspaceClient("", tmp_path / "agent_token").list_documents()
    c = WorkspaceClient("http://agent:8765", tmp_path / "missing", transport=_agent_transport([]))
    with pytest.raises(WorkspaceUnavailable, match="agent_token"):
        c.list_documents()


def test_bad_token_is_unavailable_and_never_leaked(tmp_path: Path):
    tok = tmp_path / "agent_token"
    tok.write_text("wrong-secret-value", encoding="utf-8")
    c = WorkspaceClient("http://agent:8765", tok, transport=_agent_transport([]))
    with pytest.raises(WorkspaceUnavailable) as e:
        c.list_documents()
    assert "401" in str(e.value) and "wrong-secret-value" not in str(e.value)


def test_extract_text_types():
    assert extract_text("a.txt", "héllo".encode()) == "héllo"
    assert extract_text("a.csv", b"x,y\n1,2") == "x,y\n1,2"
    assert extract_text("a.exe", b"\x00") is None
    assert extract_text("a.json", b"{}") == "{}"
