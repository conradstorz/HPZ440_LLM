import pytest

from jarvis.journal import Journal
from jarvis.policy import ALLOWED, Policy, PolicyViolation


@pytest.fixture
def policy(data_dir):
    return Policy(Journal(data_dir))


def test_allowed_set_is_exact():
    assert ALLOWED == frozenset({"read", "archive_copy", "classify", "search", "suggest", "draft",
                                 "correct", "notes_read", "notes_write", "documents_read", "obiwan_search", "obiwan_submit"})


@pytest.mark.parametrize("action", sorted(ALLOWED))
def test_allowed_actions_pass(policy, action):
    policy.check(action)


@pytest.mark.parametrize("action", ["send", "delete", "modify", "label", "unsubscribe", "http_fetch", "forward", ""])
def test_forbidden_actions_raise(policy, action):
    with pytest.raises(PolicyViolation):
        policy.check(action)


def test_filter_strips_tool_calls_and_journals(policy, data_dir):
    out = {"group": "fyi", "tool_calls": [{"name": "send_email"}], "send": {"to": "x"}, "topic": "t"}
    clean, rejected = policy.filter_model_output(out, dedup_key="gmail:a:1")
    assert clean == {"group": "fyi", "topic": "t"}
    assert rejected == ["send", "tool_calls"]
    events = Journal(data_dir).events_for("gmail:a:1")
    assert [e.kind for e in events] == ["policy_reject", "policy_reject"]
    assert {e.payload["key"] for e in events} == {"send", "tool_calls"}


def test_filter_leaves_clean_output_alone(policy):
    out = {"group": "fyi", "requested_action": "reply", "proposed_action": "none"}
    clean, rejected = policy.filter_model_output(out)
    assert clean == out and rejected == []
