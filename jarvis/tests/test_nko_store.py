import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.core.nko import NKO, NKOStatus, effective_group, sender_address, sender_domain
from jarvis.core.store import Store, VersionExists
from tests.conftest import classified, make_nko


def test_derive_increments_version_and_keeps_facts():
    v0 = make_nko()
    v1 = v0.derive(classifications=[{"group": "fyi"}], status=NKOStatus.CLASSIFIED)
    assert v1.version == 1 and v0.version == 0
    assert v1.id == v0.id and v1.subject == v0.subject and v1.dedup_key == v0.dedup_key
    assert isinstance(v1.classifications, tuple) and v1.classifications[0]["group"] == "fyi"


def test_nko_is_frozen():
    n = make_nko()
    with pytest.raises(ValidationError):
        n.subject = "x"
    with pytest.raises(AttributeError):
        n.facts.append({})
    with pytest.raises(TypeError):
        n.raw_metadata["k"] = 1


def test_helpers():
    n = make_nko(sender="Bob@Example.com")
    assert sender_address(n) == "bob@example.com" and sender_domain(n) == "example.com"
    assert effective_group(n) is None
    c = classified(n, "fyi")
    assert effective_group(c) == "fyi"
    d = c.derive(decisions=[{"from_group": "fyi", "to_group": "needs_decision"}])
    assert effective_group(d) == "needs_decision"


def test_store_round_trip(store: Store):
    v0 = make_nko()
    p = store.save_version(v0)
    assert p.name == "nko-v0.json" and store.exists(v0.dedup_key)
    v1 = classified(v0)
    store.save_version(v1)
    assert store.get_latest(v0.dedup_key).version == 1
    assert [n.version for n in store.get_versions(v0.dedup_key)] == [0, 1]
    assert store.get_version(v0.dedup_key, 0).status == NKOStatus.CAPTURED
    assert [n.dedup_key for n in store.iter_latest()] == [v0.dedup_key]
    assert store.count() == 1
    assert store.get_latest("gmail:x:missing") is None


def test_store_refuses_overwrite(store: Store):
    v0 = make_nko()
    path = store.save_version(v0)
    with pytest.raises(VersionExists):
        store.save_version(v0)
    # the refused write left the published file alone and cleaned up after itself
    d = path.parent
    assert [p.name for p in sorted(d.iterdir())] == ["nko-v0.json"]
    assert list(d.glob("*.tmp")) == []


def test_store_refuses_overwrite_even_without_the_early_check(store: Store, monkeypatch):
    """The publish step itself must refuse to clobber, not just the exists() probe that races with it."""
    v0 = make_nko()
    store.save_version(v0)
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(VersionExists):
        store.save_version(v0)


def test_store_crash_leaves_no_partial(store: Store, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "link", boom)
    with pytest.raises(OSError):
        store.save_version(make_nko())
    assert not store.exists("gmail:conradstorz@gmail.com:m1")


def test_save_raw(store: Store):
    p = store.save_raw("gmail:a:b", "attachments/abc-file.pdf", b"x")
    assert p.read_bytes() == b"x" and "gmail_a_b" in str(p)
