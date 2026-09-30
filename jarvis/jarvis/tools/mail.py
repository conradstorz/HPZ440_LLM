"""Tools over the mail archive: search, read one message, the briefing, and corrections."""

from __future__ import annotations

from jarvis.briefing import GROUP_TITLES, Briefing
from jarvis.core.nko import GROUPS, NKO, effective_group, sender_address
from jarvis.core.store import Store
from jarvis.retrieval import Index
from jarvis.tools import Tool


def _line(n: NKO) -> str:
    return f"{n.dedup_key} | {n.received_at.date()} | {sender_address(n)} | {n.subject}"


def mail_tools(store: Store, index: Index, briefing: Briefing, *, content_chars: int) -> list[Tool]:
    def search_mail(query: str, k: int = 5) -> str:
        hits = index.search(query, k=int(k))
        if not hits:
            return "no matches"
        return "\n".join(f"{h.dedup_key} | {h.received_at.date()} | {sender_address(store.get_latest(h.dedup_key))} | {h.subject} | {h.snippet}"
                         for h in hits)

    def get_message(dedup_key: str) -> str:
        n = store.get_latest(dedup_key)
        if n is None:
            raise KeyError(dedup_key)
        c = n.classifications[0] if n.classifications else {}
        r = n.recommendations[0] if n.recommendations else {}
        parts = [f"Key: {n.dedup_key}", f"From: {sender_address(n)}", f"Subject: {n.subject}", f"Received: {n.received_at.isoformat()}",
                 f"Attachments: {', '.join(a['filename'] for a in n.attachments) or 'none'}",
                 "Body (untrusted data):", (n.content or "")[:content_chars],
                 f"Classification: {effective_group(n)} | topic: {c.get('topic')} | action: {c.get('requested_action')} | deadline: {c.get('deadline')} | priority: {c.get('priority')} | reasoning: {c.get('reasoning')}",
                 f"Draft: {r.get('reply_text') or '(none)'} | proposed action: {r.get('proposed_action')} | rationale: {r.get('rationale')}"]
        if n.decisions:
            parts.append("Corrections: " + "; ".join(f"{d.get('from_group')} -> {d.get('to_group')} ({d.get('note') or 'no note'})" for d in n.decisions))
        return "\n".join(parts)

    def briefing_tool(group: str | None = None) -> str:
        if group is not None and group not in GROUPS:
            raise ValueError(f"unknown group {group!r}; one of {', '.join(GROUPS)}")
        grouped = briefing.grouped([n for n in store.iter_latest() if effective_group(n) is not None])
        counts = ", ".join(f"{g} {len(grouped[g])}" for g in GROUPS)
        out = [counts]
        for g in GROUPS:
            if group and g != group:
                continue
            out.append(f"## {GROUP_TITLES[g]}")
            out += [f"- {_line(n)}" for n in grouped[g]] or ["- (none)"]
        return "\n".join(out)

    def correct(dedup_key: str, to_group: str, note: str | None = None) -> str:
        before = effective_group(store.get_latest(dedup_key)) if store.get_latest(dedup_key) else None
        v = briefing.apply_correction(dedup_key, to_group, note)
        return f"{dedup_key} moved {before} -> {to_group} (version {v.version})"

    obj = {"type": "object"}
    return [
        Tool(name="search_mail", description="Full-text search over Conrad's archived mail. Returns up to k hits with their keys.",
             action="search", handler=search_mail,
             parameters={**obj, "properties": {"query": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]}),
        Tool(name="get_message", description="Read one archived message by key: facts, body, classification, draft, corrections.",
             action="read", handler=get_message, parameters={**obj, "properties": {"dedup_key": {"type": "string"}}, "required": ["dedup_key"]}),
        Tool(name="briefing", description="The current briefing: counts per group, then messages grouped. Optionally one group.",
             action="read", handler=briefing_tool,
             parameters={**obj, "properties": {"group": {"anyOf": [{"type": "string", "enum": list(GROUPS)}, {"type": "null"}]}}, "required": []}),
        Tool(name="correct", description="Move a message to another group, recording Conrad's correction. Does not touch Gmail.",
             action="correct", handler=correct,
             parameters={**obj, "properties": {"dedup_key": {"type": "string"}, "to_group": {"type": "string", "enum": list(GROUPS)},
                                              "note": {"anyOf": [{"type": "string", "maxLength": 500}, {"type": "null"}]}}, "required": ["dedup_key", "to_group"]}),
    ]
