import pytest
from pydantic import ValidationError

from jarvis.core.llm import FakeLLM, LLMError
from jarvis.core.nko import NKOStatus
from jarvis.draft import DRAFT_SCHEMA, DraftEntry, DraftError, draft
from jarvis.journal import Journal
from jarvis.policy import Policy
from tests.conftest import classified, make_nko

GOOD = {"reply_text": "Hi Alice, approved. Please proceed.", "proposed_action": "none", "rationale": "Approval requested."}


@pytest.fixture
def deps(data_dir):
    j = Journal(data_dir)
    return {"policy": Policy(j), "journal": j}


def test_schema_enumerates_actions():
    assert DRAFT_SCHEMA["properties"]["proposed_action"]["enum"] == ["none", "archive", "label", "unsubscribe"]


def test_draft_happy_path(deps):
    llm = FakeLLM([GOOD])
    v2 = draft(classified(make_nko()), [], llm, **deps)
    assert v2.version == 2 and v2.status == NKOStatus.DRAFTED
    r = v2.recommendations[0]
    assert r["reply_text"].startswith("Hi Alice") and r["proposed_action"] == "none" and r["model"] == "fake"
    assert [e.kind for e in deps["journal"].events_for(v2.dedup_key)] == ["draft"]
    assert "needs_decision" in llm.calls[0]["user"]


def test_noise_and_fyi_skip_the_model(deps):
    llm = FakeLLM([])
    for group in ("likely_noise", "fyi"):
        v2 = draft(classified(make_nko(f"gmail:a:{group}"), group, requested_action=None), [], llm, **deps)
        assert v2.recommendations[0]["reply_text"] is None and v2.recommendations[0]["proposed_action"] == "none"
    assert llm.calls == []


def test_fyi_with_requested_action_calls_the_model(deps):
    llm = FakeLLM([GOOD])
    draft(classified(make_nko(), "fyi", requested_action="confirm receipt"), [], llm, **deps)
    assert len(llm.calls) == 1


def test_retry_and_failure(deps):
    with pytest.raises(DraftError):
        draft(classified(make_nko()), [], FakeLLM([LLMError("a"), LLMError("b"), LLMError("c")]), **deps)
    v2 = draft(classified(make_nko("gmail:a:2")), [], FakeLLM([{"proposed_action": "delete_all"}, GOOD]), **deps)
    assert v2.recommendations[0]["proposed_action"] == "none"


def test_entry_validation():
    with pytest.raises(ValidationError):
        DraftEntry(reply_text=None, proposed_action="forward", rationale="x")


def test_reply_text_is_truncated_to_schema_limit(deps):
    llm = FakeLLM([{**GOOD, "reply_text": "x" * 5000}])
    v2 = draft(classified(make_nko()), [], llm, **deps)
    assert len(v2.recommendations[0]["reply_text"]) == 2000


def test_schema_bounds_reply_text_length():
    string_branch = next(b for b in DRAFT_SCHEMA["properties"]["reply_text"]["anyOf"] if b.get("type") == "string")
    assert string_branch["maxLength"] == 2000


def test_notes_text_appears_in_prompt(deps):
    llm = FakeLLM([GOOD])
    draft(classified(make_nko()), [], llm, notes_text="Notes from Conrad:\n1. Sign off with Conrad.", **deps)
    assert "Sign off with Conrad." in llm.calls[0]["user"]
