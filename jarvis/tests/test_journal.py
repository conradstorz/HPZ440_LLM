from datetime import UTC, date, datetime
from pathlib import Path

from jarvis.journal import Journal, JournalEvent


def test_append_and_read_by_day(data_dir: Path):
    j = Journal(data_dir)
    e = JournalEvent.new("capture", dedup_key="gmail:a:1", version=0, payload={"n": 1})
    j.append(e)
    day = e.ts.date()
    got = j.read(day)
    assert len(got) == 1 and got[0].kind == "capture" and got[0].payload == {"n": 1}
    assert (data_dir / "journal" / f"{day.isoformat()}.jsonl").exists()
    assert j.read(date(2000, 1, 1)) == []


def test_events_for_in_order_and_last_run(data_dir: Path):
    j = Journal(data_dir)
    j.append(JournalEvent(ts=datetime(2025, 9, 1, tzinfo=UTC), kind="capture", dedup_key="k", version=0, payload={}))
    j.append(JournalEvent(ts=datetime(2025, 9, 2, tzinfo=UTC), kind="run", payload={"captured": 1}))
    j.append(JournalEvent(ts=datetime(2025, 9, 3, tzinfo=UTC), kind="classify", dedup_key="k", version=1, payload={}))
    j.append(JournalEvent(ts=datetime(2025, 9, 4, tzinfo=UTC), kind="run", payload={"captured": 0}))
    assert [e.kind for e in j.events_for("k")] == ["capture", "classify"]
    assert j.last_run().payload == {"captured": 0}
    assert j.last_error_for("k") is None
    j.append(JournalEvent(ts=datetime(2025, 9, 5, tzinfo=UTC), kind="error", dedup_key="k", payload={"stage": "classify"}))
    assert j.last_error_for("k").payload["stage"] == "classify"


def test_malformed_line_is_skipped(data_dir: Path):
    j = Journal(data_dir)
    e = JournalEvent.new("run", payload={})
    j.append(e)
    f = data_dir / "journal" / f"{e.ts.date().isoformat()}.jsonl"
    f.write_text(f.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    assert len(j.read(e.ts.date())) == 1
    assert j.skipped_lines == 1


def test_last_run_none_when_empty(data_dir: Path):
    assert Journal(data_dir).last_run() is None
