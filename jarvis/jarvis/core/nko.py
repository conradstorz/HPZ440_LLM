"""The Normalized Knowledge Object. Copied from GTE and trimmed for Jarvis.

Immutable after construction. Facts come from the source (v0); every later stage
derives a new version and layers observations, classifications, recommendations,
and decisions beside the facts, never over them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from jarvis.core._frozen import FrozenDict

GROUPS = ("needs_decision", "reply_suggested", "fyi", "likely_noise")
PRIORITIES = ("high", "normal", "low")
PROPOSED_ACTIONS = ("none", "archive", "label", "unsubscribe")


class KnowledgeType(StrEnum):
    EMAIL = "email"
    DOCUMENT = "document"
    CALENDAR_EVENT = "calendar_event"


class NKOStatus(StrEnum):
    CAPTURED = "captured"
    CLASSIFIED = "classified"
    DRAFTED = "drafted"
    CORRECTED = "corrected"


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class NKO(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, validate_default=True)

    id: UUID
    knowledge_type: KnowledgeType
    source_system: str
    source_account: str
    source_identifier: str
    source_url: str | None = None
    dedup_key: str

    occurred_at: datetime | None = None
    received_at: datetime

    participants: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    subject: str | None = None
    content: str | None = None
    attachments: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    references: tuple[dict[str, Any], ...] = Field(default_factory=tuple)

    facts: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    observations: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    classifications: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    recommendations: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    decisions: tuple[dict[str, Any], ...] = Field(default_factory=tuple)

    confidence: float | None = None
    status: NKOStatus = NKOStatus.CAPTURED
    labels: tuple[str, ...] = Field(default_factory=tuple)
    policy_matches: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    raw_metadata: FrozenDict = Field(default_factory=dict)

    version: int = 0

    @classmethod
    def new(cls, **fields: Any) -> NKO:
        fields.setdefault("id", uuid4())
        fields.setdefault("received_at", utcnow())
        return cls(**fields)

    def derive(self, **changes: Any) -> NKO:
        """Return version + 1 with ``changes`` layered on. Re-validates so lists become tuples."""
        data = self.model_dump()
        data.update(changes)
        data["version"] = self.version + 1
        return NKO.model_validate(data)


class Evidence(BaseModel):
    """One retrieved prior message, in the shape stored under ``observations``."""

    nko_id: str
    dedup_key: str
    subject: str
    received_at: datetime
    snippet: str
    score: float


def effective_group(nko: NKO) -> str | None:
    if nko.decisions:
        return nko.decisions[-1]["to_group"]
    if nko.classifications:
        return nko.classifications[0]["group"]
    return None


def sender_address(nko: NKO) -> str:
    for p in nko.participants:
        if p.get("role") == "from":
            return (p.get("address") or "").lower()
    return ""


def sender_domain(nko: NKO) -> str:
    addr = sender_address(nko)
    return addr.rsplit("@", 1)[1] if "@" in addr else ""
