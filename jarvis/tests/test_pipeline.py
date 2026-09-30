from datetime import UTC, datetime, timedelta

import pytest

from jarvis.briefing import Briefing
from jarvis.core.config import Settings
from jarvis.core.llm import FakeLLM, LLMError
from jarvis.core.nko import NKOStatus, effective_group, utcnow
from jarvis.journal import Journal, JournalEvent
from jarvis.notes import Notes
from jarvis.pipeline import MAX_ATTEMPTS, PollError, run_once
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.sources.base import FakeSource
from jarvis.sources.gmail import AuthRequired
from tests.conftest import make_nko

# FakeSource now filters on ``since``; every polled fixture must be inside the default lookback window.
NOW = utcnow()

CLS = {"group": "reply_suggested", "topic": "t", "requested_action": "reply", "deadline": None, "priority": "normal", "reasoning": "r"}
DRF = {"reply_text": "ok", "proposed_action": "none", "rationale": "r"}


def _deps(data_dir, store):
    j = Journal(data_dir)
    return dict(store=store, journal=j, index=Index(data_dir, store), policy=Policy(j), briefing=Briefing(store, j),
                notes=Notes(data_dir, j), settings=Settings(data_dir=data_dir))


def test_end_to_end_three_messages(data_dir, store):
    deps = _deps(data_dir, store)
    src = FakeSource([make_nko(f"gmail:a:{i}", subject=f"S{i}", received_at=NOW) for i in range(3)])
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
    src = FakeSource([make_nko(f"gmail:a:{i}", received_at=NOW) for i in range(3)])
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
    run_once(sources=[FakeSource([make_nko("gmail:a:0", subject="Earlier", received_at=NOW)])], llm=FakeLLM([CLS, DRF]), **deps)
    deps["briefing"].apply_correction("gmail:a:0", "needs_decision", "always ask me")
    llm = FakeLLM([CLS, DRF])
    run_once(sources=[FakeSource([make_nko("gmail:a:1", subject="Later", received_at=NOW)])], llm=llm, **deps)
    assert "always ask me" in llm.calls[0]["user"]


def test_error_stage_is_capture_when_indexing_fails(data_dir, store, monkeypatch):
    deps = _deps(data_dir, store)
    monkeypatch.setattr(deps["index"], "index", lambda nko: (_ for _ in ()).throw(RuntimeError("disk")))
    s = run_once(sources=[FakeSource([make_nko("gmail:a:0", received_at=NOW)])], llm=FakeLLM([]), **deps)
    assert s.errors == 1
    assert deps["journal"].last_error_for("gmail:a:0").payload["stage"] == "capture"


def test_a_message_archived_but_never_indexed_is_indexed_on_resume(data_dir, store):
    """If index() failed after save_version, the capture block is skipped forever; the resume path must re-index."""
    deps = _deps(data_dir, store)  # Index built against an empty store, so its rebuild() indexes nothing
    store.save_version(make_nko("gmail:a:0", received_at=NOW))
    assert deps["index"].count() == 0
    s = run_once(sources=[FakeSource([])], llm=FakeLLM([CLS, DRF]), **deps)
    assert (s.captured, s.classified, s.drafted, s.errors) == (0, 1, 1, 0)
    assert deps["index"].count() == 1


def test_pending_is_deduplicated_within_one_run(data_dir, store):
    deps = _deps(data_dir, store)
    n = make_nko("gmail:a:0", received_at=NOW)
    # first run: classify fails three times -> v0 only
    run_once(sources=[FakeSource([n])], llm=FakeLLM([LLMError("a"), LLMError("b"), LLMError("c")]), **deps)
    # second run: FakeSource re-yields the same v0; it must be processed once, not twice
    llm = FakeLLM([CLS, DRF])
    s = run_once(sources=[FakeSource([n])], llm=llm, **deps)
    assert (s.classified, s.drafted, s.errors) == (1, 1, 0) and len(llm.calls) == 2
    assert sum(1 for e in deps["journal"].iter_all() if e.kind == "classify") == 1


def test_a_message_that_failed_five_times_is_skipped(data_dir, store):
    deps = _deps(data_dir, store)
    n = make_nko("gmail:a:0", received_at=NOW)
    store.save_version(n)
    for _ in range(MAX_ATTEMPTS):
        deps["journal"].append(JournalEvent.new("error", nko_id=n.id, dedup_key=n.dedup_key, version=0,
                                                payload={"stage": "classify", "message": "LLMError: x"}))
    llm = FakeLLM([])
    s = run_once(sources=[FakeSource([])], llm=llm, **deps)
    assert s.skipped == 1 and (s.classified, s.drafted, s.errors) == (0, 0, 0)
    assert llm.calls == []
    assert store.get_latest("gmail:a:0").version == 0


class ExplodingSource:
    """Yields real NKOs, then fails the way a quota wall does: from inside poll(), mid-iteration."""

    name = "gmail"

    def __init__(self, nkos, error):
        self._nkos, self._error = list(nkos), error

    def poll(self, since):
        yield from self._nkos
        raise self._error


def test_messages_yielded_before_a_poll_failure_are_kept(data_dir, store):
    deps = _deps(data_dir, store)
    src = ExplodingSource([make_nko("gmail:a:0"), make_nko("gmail:a:1")], RuntimeError("quota"))
    with pytest.raises(PollError) as e:
        run_once(sources=[src], llm=FakeLLM([CLS, DRF, CLS, DRF]), **deps)
    assert "gmail: RuntimeError: quota" in str(e.value)
    assert isinstance(e.value.__cause__, RuntimeError)
    # both messages made it all the way to v2 before the wall
    assert [store.get_latest(f"gmail:a:{i}").version for i in (0, 1)] == [2, 2]
    events = list(deps["journal"].iter_all())
    poll_errors = [ev for ev in events if ev.kind == "error" and ev.payload["stage"] == "poll"]
    assert len(poll_errors) == 1 and poll_errors[0].payload["source"] == "gmail"
    assert "RuntimeError: quota" in poll_errors[0].payload["message"]
    run = deps["journal"].last_run()
    assert run is not None and run.payload["captured"] == 2 and run.payload["errors"] == 1


def test_auth_required_on_the_first_poll_still_writes_a_run_event(data_dir, store):
    deps = _deps(data_dir, store)
    src = ExplodingSource([], AuthRequired("token.json not found"))
    with pytest.raises(PollError) as e:
        run_once(sources=[src], llm=FakeLLM([]), **deps)
    assert "AuthRequired" in str(e.value) and isinstance(e.value.__cause__, AuthRequired)
    run = deps["journal"].last_run()
    assert run is not None and run.payload["captured"] == 0 and run.payload["errors"] == 1
    poll_errors = [ev for ev in deps["journal"].iter_all() if ev.kind == "error"]
    assert len(poll_errors) == 1 and poll_errors[0].dedup_key is None  # a poll error belongs to no message
    assert poll_errors[0].payload["stage"] == "poll"


def test_a_run_stops_at_the_cap_and_the_rest_wait_for_the_next_run(data_dir, store):
    deps = _deps(data_dir, store)
    deps["settings"] = Settings(data_dir=data_dir, max_messages_per_run=2)
    src = FakeSource([make_nko(f"gmail:a:{i}", subject=f"S{i}", received_at=NOW) for i in range(3)])
    s = run_once(sources=[src], llm=FakeLLM([CLS, DRF, CLS, DRF]), **deps)
    assert (s.captured, s.classified, s.drafted) == (2, 2, 2) and s.capped is True
    assert not store.exists("gmail:a:2")
    assert deps["journal"].last_run().payload["capped"] is True
    # the same source on the next run: the first two are skipped by store.exists(), the third is captured
    s2 = run_once(sources=[src], llm=FakeLLM([CLS, DRF]), **deps)
    assert (s2.captured, s2.classified, s2.drafted) == (1, 1, 1) and s2.capped is False
    assert store.get_latest("gmail:a:2").version == 2
    # a capped run does not advance the watermark, or the backlog it left behind would fall out of the window
    assert s2.since == s.since


def test_a_poll_failure_does_not_advance_the_watermark(data_dir, store):
    deps = _deps(data_dir, store)
    with pytest.raises(PollError):
        run_once(sources=[ExplodingSource([], RuntimeError("quota"))], llm=FakeLLM([]), **deps)
    first = deps["journal"].last_run()
    assert first.payload["poll_failed"] is True
    s2 = run_once(sources=[FakeSource([])], llm=FakeLLM([]), **deps)
    assert s2.since == datetime.fromisoformat(first.payload["since"])
    # the clean run that follows does advance it
    second_run_ts = deps["journal"].last_run().ts
    s3 = run_once(sources=[FakeSource([])], llm=FakeLLM([]), **deps)
    assert s3.since == second_run_ts - timedelta(hours=1)


def test_pipeline_injects_active_notes(data_dir, store):
    deps = _deps(data_dir, store)
    deps["notes"].propose("Newsletters are noise.", "classify", "explicit")
    deps["notes"].propose("pending thing", "classify", "proposed")
    llm = FakeLLM([CLS, DRF])
    run_once(sources=[FakeSource([make_nko("gmail:a:0", received_at=NOW)])], llm=llm, **deps)
    assert "Newsletters are noise." in llm.calls[0]["user"] and "pending thing" not in llm.calls[0]["user"]
