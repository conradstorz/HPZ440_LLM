"""Source roots are only ever read: a full scan/reindex/search cycle leaves every byte and entry under a root untouched."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from obiwan.core.config import Settings
from obiwan.runtime import build_service
from tests.conftest import T0

FORBIDDEN_SUFFIXES = (".error.json", "-wal", "-shm", ".sqlite")


def _snapshot(root: Path) -> dict:
    entries: dict = {}
    for p in sorted([root, *root.rglob("*")]):
        rel = p.relative_to(root).as_posix()
        st = p.stat()
        if p.is_dir():
            entries[rel] = ("dir", st.st_mtime_ns, sorted(c.name for c in p.iterdir()))
        else:
            entries[rel] = ("file", st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return entries


def test_full_cycle_never_writes_a_source_root(tmp_path):
    root, inbox, data = tmp_path / "corpus", tmp_path / "inbox", tmp_path / "data"
    for d in (root, inbox, data, root / "notes" / "deep", root / "empty"):
        d.mkdir(parents=True, exist_ok=True)
    (root / "zebra.md").write_text("# Zebra\n\nZebras migrate across the Serengeti.\n", encoding="utf-8", newline="\n")
    (root / "notes" / "plan.txt").write_text("Plan: pay the invoice before Friday.\n", encoding="utf-8", newline="\n")
    (root / "notes" / "deep" / "log.md").write_text("# Log\n\nGiraffe enclosure opens in May.\n", encoding="utf-8", newline="\n")
    (root / "image.png").write_bytes(b"\x89PNG not really")  # unsupported
    (root / "notes" / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")  # fails extraction

    settings = Settings(_env_file=None, data_dir=data, inbox_dir=inbox, source_roots=f"corpus={root}",
                        reader_token="r", writer_token="w", commander_token="c", chunk_chars=200)
    svc = build_service(settings)
    clock = [T0]
    svc._now = lambda: clock[0]
    try:
        before = _snapshot(root)

        rep1 = svc.scan(role="writer")
        assert rep1["roots"][0]["reachable"] and rep1["roots"][0]["new"] == 4  # three good files plus the corrupt pdf; the png is skipped
        assert rep1["work"]["postponed"] + rep1["work"]["failed"] >= 1  # the root's corrupt pdf really failed extraction
        assert any(e.startswith("ExtractionError") for e in rep1["work"]["errors"])
        hit = svc.search("serengeti", 5)["results"]
        assert hit and hit[0]["location"].startswith("corpus:")  # root files were extracted and indexed
        (inbox / "memo.md").write_text("# Memo\n\nThe inbox memo mentions zebras.\n", encoding="utf-8", newline="\n")
        (inbox / "bad.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
        rep2 = svc.scan(role="writer")
        assert rep2["inbox"]["recorded"] == 1 and rep2["inbox"]["failed"] == 1
        assert (inbox / "failed" / "bad.pdf.error.json").is_file()  # the error file lands in the inbox, not the root
        clock[0] = T0 + timedelta(days=30)  # past next_attempt_at, so the retry re-reads the failed root file
        rep3 = svc.scan(role="writer")
        assert rep3["work"]["postponed"] + rep3["work"]["failed"] >= 1
        svc.reindex(role="writer")
        assert svc.search("zebra", 5)["results"]

        after = _snapshot(root)
    finally:
        svc.projection.close()
        svc.record.close()

    assert after == before
    created = [p for p in root.rglob("*") if p.name.endswith(FORBIDDEN_SUFFIXES)]
    assert created == []
    assert any(data.iterdir())  # sanity: Obi-Wan did write, just not under the root
