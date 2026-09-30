"""Wire the units: poll -> archive v0 -> index -> classify -> draft, each message isolated, one run event per pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from jarvis.briefing import Briefing
from jarvis.classify import classify
from jarvis.core.config import Settings
from jarvis.core.llm import LlamaCppClient, LLMClient
from jarvis.core.nko import NKO, sender_address, sender_domain, utcnow
from jarvis.core.run import RunSummary
from jarvis.core.store import Store
from jarvis.draft import draft
from jarvis.journal import Journal, JournalEvent
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.sources.base import Source

OVERLAP = timedelta(hours=1)


def _process(nko: NKO, *, llm: LLMClient, store: Store, journal: Journal, index: Index, policy: Policy,
             briefing: Briefing, settings: Settings, summary: RunSummary) -> None:
    """Advance one message from whatever version it has to v2. Raises on the first failing stage."""
    if not store.exists(nko.dedup_key):
        store.save_version(nko)
        journal.append(JournalEvent.new("capture", nko_id=nko.id, dedup_key=nko.dedup_key, version=0,
                                        payload={"subject": nko.subject, "attachments": len(nko.attachments)}))
        index.index(nko)
        summary.captured += 1
    current = store.get_latest(nko.dedup_key)
    corrections = briefing.corrections_for(sender_address(current), sender_domain(current))
    if not current.classifications:
        policy.check("search")
        evidence = index.search(f"{current.subject or ''} {sender_address(current)}", k=5, exclude=current.dedup_key)
        current = classify(current, evidence, corrections, llm, policy=policy, journal=journal, content_chars=settings.content_chars)
        store.save_version(current)
        summary.classified += 1
    if not current.recommendations:
        current = draft(current, corrections, llm, policy=policy, journal=journal, content_chars=settings.content_chars)
        store.save_version(current)
        summary.drafted += 1


def run_once(*, sources: list[Source], llm: LLMClient, store: Store, journal: Journal, index: Index, policy: Policy,
             briefing: Briefing, settings: Settings, now: datetime | None = None) -> RunSummary:
    policy.check("read")
    now = now or utcnow()
    last = journal.last_run()
    since = (last.ts - OVERLAP) if last else (now - timedelta(days=settings.initial_lookback_days))
    summary = RunSummary(since=since)
    pending: list[NKO] = [n for n in store.iter_latest() if not n.recommendations]
    for source in sources:
        pending.extend(source.poll(since))
    for nko in pending:
        try:
            _process(nko, llm=llm, store=store, journal=journal, index=index, policy=policy, briefing=briefing,
                     settings=settings, summary=summary)
        except Exception as e:  # noqa: BLE001 - one message must never stop the run
            summary.errors += 1
            latest = store.get_latest(nko.dedup_key)
            stage = "capture" if latest is None else "classify" if not latest.classifications else "draft"
            journal.append(JournalEvent.new("error", nko_id=nko.id, dedup_key=nko.dedup_key,
                                            version=latest.version if latest else None,
                                            payload={"stage": stage, "message": f"{type(e).__name__}: {e}"[:1000]}))
    journal.append(JournalEvent.new("run", payload={**summary.model_dump(mode="json")}))
    return summary


@dataclass
class Runtime:
    settings: Settings
    store: Store
    journal: Journal
    policy: Policy
    index: Index
    briefing: Briefing
    llm: LlamaCppClient
    sources: list[Source] = field(default_factory=list)

    def run_once(self) -> RunSummary:
        return run_once(sources=self.sources, llm=self.llm, store=self.store, journal=self.journal, index=self.index,
                        policy=self.policy, briefing=self.briefing, settings=self.settings)


def build_runtime(settings: Settings | None = None, *, with_gmail: bool = True) -> Runtime:
    s = settings or Settings()
    store = Store(s.data_dir)
    journal = Journal(s.data_dir)
    rt = Runtime(settings=s, store=store, journal=journal, policy=Policy(journal), index=Index(s.data_dir, store),
                 briefing=Briefing(store, journal), llm=LlamaCppClient(s.llm_base_url, s.llm_model, timeout=s.llm_timeout))
    if with_gmail:
        rt.sources.append(_LazyGmail(s, store))
    return rt


class _LazyGmail:
    """Defers token loading to poll() so the web app starts even before jarvis-auth.ps1 has run."""

    name = "gmail"

    def __init__(self, settings: Settings, store: Store) -> None:
        self._s, self._store = settings, store

    def poll(self, since: datetime):
        from jarvis.sources.gmail import GmailSource, GoogleGmailAPI

        api = GoogleGmailAPI(self._s.secrets_dir / "token.json")
        src = GmailSource(api, self._store, account=self._s.gmail_account, query=self._s.gmail_query,
                          max_attachment_bytes=self._s.max_attachment_bytes)
        yield from src.poll(since)
