from jarvis.retrieval import Index
from tests.conftest import make_nko


def _three(store):
    a = make_nko("gmail:c:1", subject="Invoice approval needed", content="approve the invoice by Friday")
    b = make_nko("gmail:c:2", sender="billing@utility.example", subject="September statement", content="statement attached")
    c = make_nko("gmail:c:3", sender="news@list.example", subject="Weekly newsletter", content="zebra migration photos")
    for n in (a, b, c):
        store.save_version(n)
    return a, b, c


def test_index_and_search(data_dir, store):
    a, b, c = _three(store)
    idx = Index(data_dir, store)
    for n in (a, b, c):
        idx.index(n)
    hits = idx.search("zebra", k=5)
    assert hits and hits[0].dedup_key == c.dedup_key and "zebra" in hits[0].snippet
    assert hits[0].nko_id == str(c.id) and hits[0].subject == "Weekly newsletter"
    assert idx.search("invoice", exclude=a.dedup_key) == []
    assert idx.search("", k=5) == []
    assert idx.count() == 3


def test_reindex_same_nko_does_not_duplicate(data_dir, store):
    idx = Index(data_dir, store)
    a, _, _ = _three(store)
    idx.index(a)
    idx.index(a)
    assert idx.count() == 1


def test_rebuild_from_store_gives_identical_results(data_dir, store):
    a, b, c = _three(store)
    idx = Index(data_dir, store)
    for n in (a, b, c):
        idx.index(n)
    before = [(e.dedup_key, e.snippet) for e in idx.search("statement invoice")]
    idx.close()
    (data_dir / "index" / "mail.sqlite").unlink()
    idx = Index(data_dir, store)
    assert idx.count() == 3
    assert idx.rebuild() == 3
    assert [(e.dedup_key, e.snippet) for e in idx.search("statement invoice")] == before


def test_schema_mismatch_triggers_rebuild(data_dir, store):
    _three(store)
    idx = Index(data_dir, store)
    idx.rebuild()
    idx._conn.execute("PRAGMA user_version = 999")
    idx._conn.commit()
    idx.close()
    idx = Index(data_dir, store)
    assert idx.count() == 3
