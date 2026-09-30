import pytest

from jarvis.briefing import Briefing
from jarvis.core.nko import NKOStatus, effective_group
from jarvis.journal import Journal
from tests.conftest import classified, make_nko


@pytest.fixture
def b(data_dir, store):
    return Briefing(store, Journal(data_dir))


def _seed(store):
    out = []
    for i, g in enumerate(["needs_decision", "reply_suggested", "fyi", "likely_noise"]):
        n = classified(make_nko(f"gmail:a:{i}", subject=f"Subject {g}"), g)
        n = n.derive(recommendations=[{"reply_text": "Hi Alice, approved." if g == "reply_suggested" else None, "proposed_action": "none",
                                       "rationale": "r", "model": "fake", "at": "t"}], status=NKOStatus.DRAFTED)
        store.save_version(n)
        out.append(n)
    return out


def test_render_groups(b, store):
    nkos = _seed(store)
    html = b.render(nkos, {})
    for heading in ("Needs your decision", "Reply suggested", "For your information", "Likely noise"):
        assert heading in html
    assert html.index("Subject needs_decision") < html.index("Subject reply_suggested") < html.index("Subject fyi")
    assert "asks for approval" in html and "Hi Alice, approved." in html
    assert "/message/gmail:a:0" in html


def test_apply_correction(b, store, data_dir):
    n = _seed(store)[2]
    v = b.apply_correction(n.dedup_key, "needs_decision", "this matters")
    assert v.version == n.version + 1 and v.status == NKOStatus.CORRECTED
    assert v.decisions[-1]["from_group"] == "fyi" and v.decisions[-1]["to_group"] == "needs_decision" and v.decisions[-1]["note"] == "this matters"
    assert v.classifications == n.classifications and v.recommendations == n.recommendations
    assert effective_group(store.get_latest(n.dedup_key)) == "needs_decision"
    ev = Journal(data_dir).events_for(n.dedup_key)
    assert [e.kind for e in ev] == ["correction"] and ev[0].payload["to_group"] == "needs_decision"
    html = b.render(list(store.iter_latest()), {})
    assert html.index("Subject fyi") < html.index("<h2>Reply suggested")


def test_apply_correction_rejects_bad_group(b, store):
    _seed(store)
    with pytest.raises(ValueError):
        b.apply_correction("gmail:a:0", "spam", None)
    with pytest.raises(KeyError):
        b.apply_correction("gmail:a:missing", "fyi", None)


def test_corrections_for(b, store):
    _seed(store)
    b.apply_correction("gmail:a:0", "fyi", "n1")
    b.apply_correction("gmail:a:1", "likely_noise", None)
    got = b.corrections_for("alice@example.com", "example.com")
    assert len(got) == 2 and {c["to_group"] for c in got} == {"fyi", "likely_noise"}
    assert got[0]["subject"] and "from_group" in got[0]
    assert b.corrections_for("nobody@else.example", "else.example") == []


def test_render_unprocessed_and_message(b, store, data_dir):
    n = make_nko("gmail:a:err", subject="Broken one")
    store.save_version(n)
    j = Journal(data_dir)
    from jarvis.journal import JournalEvent
    e = JournalEvent.new("error", dedup_key=n.dedup_key, payload={"stage": "classify", "message": "timeout"})
    j.append(e)
    html = b.render([n], {n.dedup_key: e})
    assert "Unprocessed" in html and "Broken one" in html and "timeout" in html
    page = b.render_message(n, store.get_versions(n.dedup_key), j.events_for(n.dedup_key))
    assert "nko-v0" in page or "Version 0" in page
    assert "error" in page
