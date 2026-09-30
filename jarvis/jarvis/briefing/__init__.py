"""Render the grouped briefing and record corrections. Corrections are new NKO versions plus a journal event."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from jarvis.core.nko import GROUPS, NKO, NKOStatus, effective_group, sender_address, sender_domain, utcnow
from jarvis.core.store import Store
from jarvis.journal import Journal, JournalEvent

GROUP_TITLES = {
    "needs_decision": "Needs your decision",
    "reply_suggested": "Reply suggested",
    "fyi": "For your information",
    "likely_noise": "Likely noise",
}


class Briefing:
    def __init__(self, store: Store, journal: Journal) -> None:
        self._store, self._journal = store, journal
        self._env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                                autoescape=select_autoescape(["html"]))
        self._env.globals.update(GROUP_TITLES=GROUP_TITLES, GROUPS=GROUPS, effective_group=effective_group,
                                 sender_address=sender_address)

    @staticmethod
    def grouped(nkos: list[NKO]) -> dict[str, list[NKO]]:
        out: dict[str, list[NKO]] = {g: [] for g in GROUPS}
        for n in sorted(nkos, key=lambda n: n.received_at, reverse=True):
            g = effective_group(n)
            if g in out:
                out[g].append(n)
        return out

    def render(self, nkos: list[NKO], errors: dict[str, JournalEvent]) -> str:
        processed = [n for n in nkos if effective_group(n) is not None]
        unprocessed = [(n, errors.get(n.dedup_key)) for n in nkos if effective_group(n) is None]
        return self._env.get_template("briefing.html").render(groups=self.grouped(processed), unprocessed=unprocessed,
                                                              total=len(nkos))

    def render_message(self, nko: NKO, versions: list[NKO], events: list[JournalEvent]) -> str:
        return self._env.get_template("message.html").render(nko=nko, versions=versions, events=events)

    def apply_correction(self, dedup_key: str, to_group: str, note: str | None) -> NKO:
        if to_group not in GROUPS:
            raise ValueError(f"unknown group {to_group!r}")
        latest = self._store.get_latest(dedup_key)
        if latest is None:
            raise KeyError(dedup_key)
        decision = {"from_group": effective_group(latest), "to_group": to_group, "note": note or None, "at": utcnow().isoformat()}
        v = latest.derive(decisions=[*latest.decisions, decision], status=NKOStatus.CORRECTED)
        self._store.save_version(v)
        self._journal.append(JournalEvent.new("correction", nko_id=v.id, dedup_key=v.dedup_key, version=v.version, payload=decision))
        return v

    def corrections_for(self, sender: str, domain: str, limit: int = 5) -> list[dict]:
        sender, domain = sender.lower(), domain.lower()
        hits: list[tuple[str, dict]] = []
        for n in self._store.iter_latest():
            if not n.decisions:
                continue
            if sender_address(n) == sender or (domain and sender_domain(n) == domain):
                for d in n.decisions:
                    hits.append((d.get("at", ""), {"subject": n.subject, **d}))
        hits.sort(key=lambda t: t[0], reverse=True)
        return [d for _, d in hits[:limit]]
