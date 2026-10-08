import threading
from datetime import timedelta

import pytest

from obiwan.record import Record
from obiwan.work import WorkQueue, backoff
from tests.conftest import T0


@pytest.fixture
def q(data_dir):
    r = Record(data_dir / "record.sqlite")
    yield WorkQueue(r)
    r.close()


@pytest.fixture
def record_and_q(data_dir):
    r = Record(data_dir / "record.sqlite")
    yield r, WorkQueue(r)
    r.close()


def test_enqueue_is_idempotent_per_kind_and_target(q):
    assert q.enqueue("extract", "d1", now=T0) is True
    assert q.enqueue("extract", "d1", now=T0) is False
    assert q.enqueue("extract", "d2", now=T0) is True
    assert q.counts() == {"pending": 2, "failed": 0, "done": 0}


def test_claim_leases_and_a_second_claim_waits(q):
    q.enqueue("extract", "d1", now=T0)
    item = q.claim(now=T0, lease_seconds=300)
    assert item.target == "d1" and item.state == "leased" and item.lease_until == T0 + timedelta(seconds=300)
    assert q.claim(now=T0, lease_seconds=300) is None
    assert q.counts()["pending"] == 1  # leased counts as pending work, not as done


def test_an_expired_lease_is_reclaimed(q):
    q.enqueue("extract", "d1", now=T0)
    q.claim(now=T0, lease_seconds=300)
    assert q.claim(now=T0 + timedelta(seconds=299), lease_seconds=300) is None
    again = q.claim(now=T0 + timedelta(seconds=300), lease_seconds=300)
    assert again is not None and again.target == "d1"


def test_complete_marks_done(q):
    q.enqueue("extract", "d1", now=T0)
    item = q.claim(now=T0, lease_seconds=300)
    q.complete(item.id, now=T0)
    assert q.counts() == {"pending": 0, "failed": 0, "done": 1}
    assert q.claim(now=T0 + timedelta(days=1), lease_seconds=300) is None


def test_fail_postpones_with_backoff_then_gives_up(q):
    q.enqueue("extract", "d1", now=T0)
    item = q.claim(now=T0, lease_seconds=300)
    assert q.fail(item.id, "RootUnavailable: nope", now=T0, max_attempts=3) is False
    assert q.claim(now=T0, lease_seconds=300) is None  # not retried in a tight loop
    item = q.claim(now=T0 + backoff(1), lease_seconds=300)
    assert item.attempts == 1 and item.last_error == "RootUnavailable: nope"
    assert q.fail(item.id, "again", now=T0, max_attempts=3) is False
    item = q.claim(now=T0 + backoff(2), lease_seconds=300)
    assert q.fail(item.id, "third", now=T0, max_attempts=3) is True
    assert q.counts() == {"pending": 0, "failed": 1, "done": 0}
    assert [w.last_error for w in q.failed(limit=5)] == ["third"]
    assert q.claim(now=T0 + timedelta(days=30), lease_seconds=300) is None


def test_failing_an_unknown_item_is_a_clear_error(q):
    with pytest.raises(KeyError, match="no work item 999"):
        q.fail(999, "x", now=T0, max_attempts=3)


def test_a_fail_from_another_thread_is_not_swallowed_by_an_open_transaction(record_and_q):
    r, q = record_and_q
    q.enqueue("extract", "d1", now=T0)
    item = q.claim(now=T0, lease_seconds=300)
    started, done = threading.Event(), threading.Event()

    def other_thread():
        started.set()
        q.fail(item.id, "x", now=T0, max_attempts=5)
        done.set()

    t = threading.Thread(target=other_thread)
    with pytest.raises(RuntimeError):
        with r.transaction():
            t.start()
            started.wait(timeout=5)
            assert not done.wait(timeout=0.2)  # blocked on the lock, not folded into this transaction
            raise RuntimeError("roll back only this transaction")
    t.join(timeout=5)
    assert done.is_set()
    row = r.conn.execute("SELECT attempts, last_error FROM work WHERE id = ?", (item.id,)).fetchone()
    assert row["attempts"] == 1 and row["last_error"] == "x"


def test_backoff_doubles_and_is_capped():
    assert backoff(1) == timedelta(minutes=2)
    assert backoff(2) == timedelta(minutes=4)
    assert backoff(3) == timedelta(minutes=8)
    assert backoff(20) == timedelta(hours=24)
