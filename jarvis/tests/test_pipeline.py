from datetime import UTC, datetime, timedelta

from jarvis.briefing import Briefing
from jarvis.core.config import Settings
from jarvis.core.llm import FakeLLM, LLMError
from jarvis.core.nko import NKOStatus, effective_group
from jarvis.journal import Journal, JournalEvent
from jarvis.pipeline import run_once
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.sources.base import FakeSource
from tests.conftest import make_nko

CLS = {"group": "reply_suggested", "topic": "t", "requested_action": "reply", "deadline": None, "priority": "normal", "reasoning": "r"}
DRF = {"reply_text": "ok", "proposed_action": "none", "rationale": "r"}


def _deps(data_dir, store):
    j = Journal(data_dir)
    return dict(store=store, journal=j, index=Index(data_dir, store), policy=Policy(j), briefing=Briefing(store, j),
                settings=Settings(data_dir=data_dir))


def test_end_to_end_three_messages(data_dir, store):
    deps = _deps(data_dir, store)
    src = FakeSource([make_nko(f"gmail:a:{i}", subject=f"S{i}") for i in range(3)])
    llm = FakeLLM([CLS, DRF, CLS, DRF, CLS, DRF])
    s = run_once(sources=[src], llm=llm, **deps)
    assert (s.captured, s.classified, s.drafted, s.errors) == (3, 3, 3, 0)
    latest = list(store.iter_latest())
    assert all(n.version == 2 and n.status == NKOStatus.DRAFTED for n in latest)
    kinds = sorted(e.kind for e in deps["journal"].iter_all())
    assert kinds.count("capture") == 3 and kinds.count("classify") == 3 and kinds.count("draft") == 3 and kinds.count("run") == 1
    assert deps["journal"].last_run().payload["captured"] == 3
    assert deps["index"].count() == 3
    # later messages see earlier ones as evidence
    assert latest[2].observations and latest[2].observations[0]["dedup_key"] in {"gmail:a:0", "gmail:a:1"}


def test_one_failure_does_not_stop_the_run_and_is_retried(data_dir, store):
    deps = _deps(data_dir, store)
    src = FakeSource([make_nko(f"gmail:a:{i}") for i in range(3)])
    llm = FakeLLM([CLS, DRF, LLMError("x"), LLMError("y"), LLMError("z"), CLS, DRF])
    s = run_once(sources=[src], llm=llm, **deps)
    assert (s.captured, s.classified, s.drafted, s.errors) == (3, 2, 2, 1)
    assert store.get_latest("gmail:a:1").version == 0
    err = deps["journal"].last_error_for("gmail:a:1")
    assert err.payload["stage"] == "classify"
    # second run: FakeSource yields the same three; store.exists() makes the pipeline skip 0 and 2 and resume 1
    llm2 = FakeLLM([CLS, DRF])
    s2 = run_once(sources=[src], llm=llm2, **deps)
    assert (s2.captured, s2.classified, s2.drafted, s2.errors) == (0, 1, 1, 0)
    assert store.get_latest("gmail:a:1").version == 2 and len(llm2.calls) == 2


def test_since_defaults_then_uses_last_run(data_dir, store):
    deps = _deps(data_dir, store)
    now = datetime(2025, 9, 30, 12, tzinfo=UTC)
    s = run_once(sources=[FakeSource([])], llm=FakeLLM([]), now=now, **deps)
    assert s.since == now - timedelta(days=7)
    first_run_ts = deps["journal"].last_run().ts
    s2 = run_once(sources=[FakeSource([])], llm=FakeLLM([]), now=now + timedelta(hours=2), **deps)
    assert s2.since == first_run_ts - timedelta(hours=1)


def test_corrections_reach_the_prompt(data_dir, store):
    deps = _deps(data_dir, store)
    run_once(sources=[FakeSource([make_nko("gmail:a:0", subject="Earlier")])], llm=FakeLLM([CLS, DRF]), **deps)
    deps["briefing"].apply_correction("gmail:a:0", "needs_decision", "always ask me")
    llm = FakeLLM([CLS, DRF])
    run_once(sources=[FakeSource([make_nko("gmail:a:1", subject="Later")])], llm=llm, **deps)
    assert "always ask me" in llm.calls[0]["user"]


def test_error_stage_is_capture_when_indexing_fails(data_dir, store, monkeypatch):
    deps = _deps(data_dir, store)
    monkeypatch.setattr(deps["index"], "index", lambda nko: (_ for _ in ()).throw(RuntimeError("disk")))
    s = run_once(sources=[FakeSource([make_nko("gmail:a:0")])], llm=FakeLLM([]), **deps)
    assert s.errors == 1
    assert deps["journal"].last_error_for("gmail:a:0").payload["stage"] == "capture"


def test_pending_is_deduplicated_within_one_run(data_dir, store):
    deps = _deps(data_dir, store)
    n = make_nko("gmail:a:0")
    # first run: classify fails three times -> v0 only
    run_once(sources=[FakeSource([n])], llm=FakeLLM([LLMError("a"), LLMError("b"), LLMError("c")]), **deps)
    # second run: FakeSource re-yields the same v0; it must be processed once, not twice
    llm = FakeLLM([CLS, DRF])
    s = run_once(sources=[FakeSource([n])], llm=llm, **deps)
    assert (s.classified, s.drafted, s.errors) == (1, 1, 0) and len(llm.calls) == 2
    assert sum(1 for e in deps["journal"].iter_all() if e.kind == "classify") == 1
