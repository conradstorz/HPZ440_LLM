from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jarvis.classify import CLASSIFICATION_SCHEMA, ClassificationEntry, ClassifyError, build_prompt, classify
from jarvis.core.llm import FakeLLM, LLMError
from jarvis.core.nko import Evidence, NKOStatus
from jarvis.journal import Journal
from jarvis.policy import Policy
from tests.conftest import make_nko

GOOD = {"group": "needs_decision", "topic": "invoice", "requested_action": "approve invoice", "deadline": "2025-10-03",
        "priority": "high", "reasoning": "Sender asks for approval by Friday."}
EV = [Evidence(nko_id="x", dedup_key="gmail:a:0", subject="Prior invoice", received_at=datetime(2025, 9, 1, tzinfo=UTC),
               snippet="last month's invoice was approved", score=1.0)]
CORR = [{"subject": "Old invoice", "from_group": "fyi", "to_group": "needs_decision", "note": "invoices need me"}]


@pytest.fixture
def deps(data_dir):
    j = Journal(data_dir)
    return {"policy": Policy(j), "journal": j}


def test_schema_enumerates_groups_and_priorities():
    assert CLASSIFICATION_SCHEMA["properties"]["group"]["enum"] == ["needs_decision", "reply_suggested", "fyi", "likely_noise"]
    assert CLASSIFICATION_SCHEMA["properties"]["priority"]["enum"] == ["high", "normal", "low"]
    assert CLASSIFICATION_SCHEMA["additionalProperties"] is False


def test_classify_happy_path(deps):
    llm = FakeLLM([GOOD])
    v1 = classify(make_nko(), EV, CORR, llm, **deps)
    assert v1.version == 1 and v1.status == NKOStatus.CLASSIFIED
    c = v1.classifications[0]
    assert c["group"] == "needs_decision" and c["deadline"] == "2025-10-03" and c["model"] == "fake" and "at" in c
    assert v1.observations[0]["dedup_key"] == "gmail:a:0"
    assert [e.kind for e in deps["journal"].events_for(v1.dedup_key)] == ["classify"]
    prompt = llm.calls[0]["user"]
    assert "last month's invoice was approved" in prompt and "invoices need me" in prompt
    assert "untrusted" in llm.calls[0]["system"].lower()


def test_content_is_truncated(deps):
    llm = FakeLLM([GOOD])
    classify(make_nko(content="x" * 10000), EV, [], llm, content_chars=100, **deps)
    assert "x" * 101 not in llm.calls[0]["user"]


def test_retries_then_succeeds(deps):
    llm = FakeLLM([LLMError("timeout"), {"group": "bogus"}, GOOD])
    v1 = classify(make_nko(), [], [], llm, **deps)
    assert v1.classifications[0]["group"] == "needs_decision" and len(llm.calls) == 3


def test_three_failures_raise(deps):
    llm = FakeLLM([LLMError("a"), LLMError("b"), LLMError("c")])
    with pytest.raises(ClassifyError):
        classify(make_nko(), [], [], llm, **deps)


def test_tool_calls_are_stripped_and_journaled(deps):
    llm = FakeLLM([{**GOOD, "tool_calls": [{"name": "send_email"}]}])
    v1 = classify(make_nko(), [], [], llm, **deps)
    assert v1.classifications[0]["group"] == "needs_decision"
    kinds = [e.kind for e in deps["journal"].events_for(v1.dedup_key)]
    assert kinds == ["policy_reject", "classify"]


def test_entry_validation():
    with pytest.raises(ValidationError):
        ClassificationEntry(**{**GOOD, "priority": "urgent"})
    e = ClassificationEntry(**{**GOOD, "deadline": None, "requested_action": None})
    assert e.deadline is None
