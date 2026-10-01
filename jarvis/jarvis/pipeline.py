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
from jarvis.agent import Agent
from jarvis.journal import Journal, JournalEvent
from jarvis.notes import Notes
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.sources.base import Source
from jarvis.sources.workspace import WorkspaceClient
from jarvis.tools import ToolRegistry
from jarvis.tools.registry import build_registry

OVERLAP = timedelta(hours=1)
# A message that has failed this many times is left alone so one poisoned message cannot burn every run.
MAX_ATTEMPTS = 5


class PollError(Exception):
    """A source's poll() failed. Raised after the run event is written so nothing already captured is lost."""


def _process(nko: NKO, *, llm: LLMClient, store: Store, journal: Journal, index: Index, policy: Policy,
             briefing: Briefing, settings: Settings, summary: RunSummary, stage: list[str],
             corrections_cache: dict[tuple[str, str], list[dict]], notes_classify: str = "",
             notes_draft: str = "") -> None:
    """Advance one message from whatever version it has to v2. Raises on the first failing stage."""
    stage[0] = "capture"
    newly_captured = False
    if not store.exists(nko.dedup_key):
        store.save_version(nko)
        journal.append(JournalEvent.new("capture", nko_id=nko.id, dedup_key=nko.dedup_key, version=0,
                                        payload={"subject": nko.subject, "attachments": len(nko.attachments)}))
        index.index(nko)
        newly_captured = True
        summary.captured += 1
    current = store.get_latest(nko.dedup_key)
    if not newly_captured:
        # An earlier run may have died between save_version and index(); nothing would ever index this message
        # again, because the capture block is skipped from now on. index() is idempotent, so just redo it.
        index.index(current)
    stage[0] = "classify"
    cache_key = (sender_address(current), sender_domain(current))
    if cache_key not in corrections_cache:
        corrections_cache[cache_key] = briefing.corrections_for(*cache_key)
    corrections = corrections_cache[cache_key]
    if not current.classifications:
        policy.check("search")
        evidence = index.search(f"{current.subject or ''} {sender_address(current)}", k=5, exclude=current.dedup_key)
        current = classify(current, evidence, corrections, llm, policy=policy, journal=journal,
                           content_chars=settings.content_chars, notes_text=notes_classify)
        store.save_version(current)
        summary.classified += 1
    stage[0] = "draft"
    if not current.recommendations:
        current = draft(current, corrections, llm, policy=policy, journal=journal,
                        content_chars=settings.content_chars, notes_text=notes_draft)
        store.save_version(current)
        summary.drafted += 1


def _next_since(last: JournalEvent | None, now: datetime, settings: Settings) -> datetime:
    """The poll window start for this run.

    A run that hit the per-run cap or died mid-poll did not finish listing its window, so the watermark must not
    advance: GmailSource turns ``since`` into ``after:YYYY/MM/DD``, and advancing it would strand the backlog the
    capped run deliberately left behind.
    """
    if last is None:
        return now - timedelta(days=settings.initial_lookback_days)
    if last.payload.get("capped") is True or last.payload.get("poll_failed") is True:
        previous = last.payload.get("since")
        if isinstance(previous, datetime):
            return previous
        if isinstance(previous, str):
            try:
                return datetime.fromisoformat(previous)
            except ValueError:
                pass  # an unreadable watermark is no reason to refuse the run; fall back to the overlap window
    return last.ts - OVERLAP


def run_once(*, sources: list[Source], llm: LLMClient, store: Store, journal: Journal, index: Index, policy: Policy,
             briefing: Briefing, notes: Notes, settings: Settings, now: datetime | None = None) -> RunSummary:
    policy.check("read")
    # Rendered once per run: the note set cannot change mid-run, and every message in the run must see the same rules.
    notes_classify, notes_draft = notes.render_for_prompt("classify"), notes.render_for_prompt("draft")
    now = now or utcnow()
    summary = RunSummary(since=_next_since(journal.last_run(), now, settings))
    since = summary.since
    seen: set[str] = set()
    pending: list[NKO] = []
    for nko in [n for n in store.iter_latest() if not n.recommendations]:
        if nko.dedup_key in seen:
            continue
        seen.add(nko.dedup_key)
        if journal.error_count_for(nko.dedup_key) >= MAX_ATTEMPTS:
            summary.skipped += 1  # give up retrying; it stays in Unprocessed with its last error
            continue
        pending.append(nko)
    corrections_cache: dict[tuple[str, str], list[dict]] = {}

    def handle(nko: NKO) -> None:
        """Advance one message, isolating its failure. Never raises."""
        stage = ["capture"]
        try:
            _process(nko, llm=llm, store=store, journal=journal, index=index, policy=policy, briefing=briefing,
                     settings=settings, summary=summary, stage=stage, corrections_cache=corrections_cache,
                     notes_classify=notes_classify, notes_draft=notes_draft)
        except Exception as e:  # noqa: BLE001 - one message must never stop the run
            summary.errors += 1
            latest = store.get_latest(nko.dedup_key)
            journal.append(JournalEvent.new("error", nko_id=nko.id, dedup_key=nko.dedup_key,
                                            version=latest.version if latest else None,
                                            payload={"stage": stage[0], "message": f"{type(e).__name__}: {e}"[:1000]}))

    for nko in pending:  # store-derived resumes first; they cost no API calls and do not count against the cap
        handle(nko)
    # Polled messages are processed as they arrive: every one is durable before the next is fetched, so a quota
    # wall mid-poll costs at most the message in flight instead of the whole run.
    failure: Exception | None = None
    failed_source = ""
    for source in sources:
        if failure is not None or summary.capped:
            break
        polled = iter(source.poll(since))
        while True:
            if summary.captured >= settings.max_messages_per_run:
                summary.capped = True  # leave the rest for the next run; the generator is abandoned unadvanced
                break
            try:
                nko = next(polled)
            except StopIteration:  # must precede the bare Exception arm: StopIteration is an Exception
                break
            except Exception as e:  # noqa: BLE001 - the source itself failed; stop polling but keep what we have
                failure, failed_source = e, source.name
                summary.errors += 1
                summary.poll_failed = True
                journal.append(JournalEvent.new("error", payload={"stage": "poll", "source": source.name,
                                                                  "message": f"{type(e).__name__}: {e}"[:1000]}))
                break
            if nko.dedup_key in seen:
                continue
            seen.add(nko.dedup_key)
            handle(nko)
    journal.append(JournalEvent.new("run", payload={**summary.model_dump(mode="json")}))
    if failure is not None:
        raise PollError(f"{failed_source}: {type(failure).__name__}: {failure}") from failure
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
    notes: Notes
    workspace: WorkspaceClient
    tools: ToolRegistry
    agent: Agent
    sources: list[Source] = field(default_factory=list)

    def run_once(self) -> RunSummary:
        return run_once(sources=self.sources, llm=self.llm, store=self.store, journal=self.journal, index=self.index,
                        policy=self.policy, briefing=self.briefing, notes=self.notes, settings=self.settings)

    def respond(self, messages: list[dict], conversation_id: str | None = None):
        """Positional signature the OpenAI router expects."""
        return self.agent.respond(messages, conversation_id=conversation_id)


def build_runtime(settings: Settings | None = None, *, with_gmail: bool = True) -> Runtime:
    s = settings or Settings()
    store = Store(s.data_dir)
    journal = Journal(s.data_dir)
    policy = Policy(journal)
    index = Index(s.data_dir, store)
    briefing = Briefing(store, journal)
    notes = Notes(s.data_dir, journal)
    notes.expire_pending()  # a pending note nobody confirmed within a day is retired before anything reads it
    llm = LlamaCppClient(s.llm_base_url, s.llm_model, timeout=s.llm_timeout)
    # The token is read per request, not here, so the app starts before jarvis-agent-token.ps1 has ever run.
    workspace = WorkspaceClient(s.workspace_agent_url, s.secrets_dir / "agent_token",
                                max_document_bytes=s.max_document_bytes, max_pdf_pages=s.max_pdf_pages)
    tools = build_registry(policy, journal, store=store, index=index, briefing=briefing, notes=notes,
                           workspace=workspace, content_chars=s.content_chars)
    rt = Runtime(settings=s, store=store, journal=journal, policy=policy, index=index, briefing=briefing, llm=llm,
                 notes=notes, workspace=workspace, tools=tools,
                 agent=Agent(llm, tools, notes, journal, context_tokens=s.context_tokens))
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
