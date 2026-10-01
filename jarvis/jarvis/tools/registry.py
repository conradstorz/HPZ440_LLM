"""Assemble the full tool registry for the agent."""

from __future__ import annotations

from jarvis.briefing import Briefing
from jarvis.core.store import Store
from jarvis.journal import Journal
from jarvis.notes import Notes
from jarvis.policy import Policy
from jarvis.retrieval import Index
from jarvis.tools import ToolRegistry
from jarvis.tools.documents import Workspace, document_tools
from jarvis.tools.mail import mail_tools
from jarvis.tools.teach import note_tools


def build_registry(policy: Policy, journal: Journal, *, store: Store, index: Index, briefing: Briefing, notes: Notes,
                   workspace: Workspace, content_chars: int) -> ToolRegistry:
    return ToolRegistry(policy, journal, [*mail_tools(store, index, briefing, content_chars=content_chars), *note_tools(notes),
                                          *document_tools(workspace, content_chars=content_chars)])
