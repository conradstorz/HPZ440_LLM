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
