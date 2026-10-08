from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.core.llm import FakeLLM
from jarvis.core.nko import NKO, KnowledgeType, NKOStatus
from jarvis.core.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_nko(key: str = "gmail:conradstorz@gmail.com:m1", *, sender: str = "alice@example.com",
             subject: str = "Invoice approval needed", content: str = "Can you approve the invoice by Friday?",
             received_at: datetime | None = None, **extra) -> NKO:
    return NKO.new(
        knowledge_type=KnowledgeType.EMAIL, source_system="gmail", source_account="conradstorz@gmail.com",
        source_identifier=key.rsplit(":", 1)[1], dedup_key=key,
        received_at=received_at or datetime(2025, 9, 29, 20, 0, tzinfo=UTC),
        participants=[{"role": "from", "name": "", "address": sender}, {"role": "to", "name": "", "address": "conradstorz@gmail.com"}],
        subject=subject, content=content, status=NKOStatus.CAPTURED, **extra,
    )


def classified(nko: NKO, group: str = "needs_decision", requested_action: str | None = "approve invoice") -> NKO:
    return nko.derive(classifications=[{"group": group, "topic": "invoice", "requested_action": requested_action,
                                        "deadline": "2025-10-03", "priority": "high", "reasoning": "asks for approval",
                                        "model": "fake", "at": "2025-09-30T00:00:00+00:00"}],
                      status=NKOStatus.CLASSIFIED)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def store(data_dir: Path) -> Store:
    return Store(data_dir)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


class FakeWorkspace:
    """Stands in for WorkspaceClient: no HTTP, no token, deterministic listings."""

    def __init__(self, docs=None, text="hello doc"):
        self.docs = docs if docs is not None else [{"name": "notes.md", "folder": "C:/Docs", "size": 9, "mtime": "2026-09-30T00:00:00", "sha256": "abc123def456" + "0" * 52}]
        self.text = text
        self.calls = []

    def list_documents(self, glob="*"):
        self.calls.append(("list", glob))
        return self.docs

    def read_document(self, sha256):
        self.calls.append(("read", sha256))
        return self.docs[0], self.text


class FakeKnowledge:
    """Stands in for ObiwanClient: records calls, returns canned provenance-bearing results."""

    def __init__(self, results=None, coverage=None):
        self.calls = []
        self.results = results if results is not None else [
            {"chunk_id": "d1-0", "doc_id": "d1", "subject_id": "f1", "version_no": 1, "origin": "source", "attestation": None,
             "title": "zebra.md", "location": "corpus:zebra.md", "root": "corpus", "path": "zebra.md", "seq": 0, "start_char": 0,
             "end_char": 40, "score": 2.5, "snippet": "Zebras migrate", "content": "Zebras migrate across the Serengeti."},
            {"chunk_id": "d2-0", "doc_id": "d2", "subject_id": "m1", "version_no": 1, "origin": "machine", "attestation": None,
             "title": None, "location": "machine:m1", "root": None, "path": None, "seq": 0, "start_char": 0, "end_char": 20,
             "score": 1.0, "snippet": "prefers zebras", "content": "Conrad prefers zebras."},
            {"chunk_id": "d3-0", "doc_id": "d3", "subject_id": "h1", "version_no": 1, "origin": "human", "attestation": "relayed",
             "title": None, "location": "human:h1", "root": None, "path": None, "seq": 0, "start_char": 0, "end_char": 20,
             "score": 0.5, "snippet": "NAS basement", "content": "The NAS is in the basement."}]
        self.coverage = coverage if coverage is not None else {"documents": 3, "documents_indexed": 3, "chunks": 5, "chunks_indexed": 5,
                                                                "work_pending": 0, "work_failed": 0, "complete": True}

    def search(self, query, k=8):
        self.calls.append(("search", query, k))
        return {"query": query, "results": self.results[:k], "coverage": self.coverage}

    def submit(self, content, title=None):
        self.calls.append(("submit", content, title))
        return {"subject_id": "m-new", "doc_id": "d-new", "version_no": 1, "origin": "machine", "attestation": None}

    def relay(self, content, conversation_ref, title=None):
        self.calls.append(("relay", content, conversation_ref, title))
        return {"subject_id": "h-new", "doc_id": "d-new2", "version_no": 1, "origin": "human", "attestation": "relayed"}
