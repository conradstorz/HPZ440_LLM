"""The permission gate. Phase 1 (Observe): read, archive, classify, search, suggest, draft. Nothing outbound."""

from __future__ import annotations

from jarvis.journal import Journal, JournalEvent

ALLOWED = frozenset({"read", "archive_copy", "classify", "search", "suggest", "draft"})

# Keys a model response may not carry: anything shaped like a tool call or an outbound verb.
FORBIDDEN_KEYS = frozenset({"tool_calls", "function_call", "action", "send", "forward", "delete", "label", "modify"})


class PolicyViolation(Exception):
    pass


class Policy:
    def __init__(self, journal: Journal) -> None:
        self._journal = journal

    def check(self, action: str) -> None:
        if action not in ALLOWED:
            raise PolicyViolation(f"action {action!r} is not permitted in permission stage 1 (Observe)")

    def filter_model_output(self, output: dict, *, dedup_key: str | None = None) -> tuple[dict, list[str]]:
        rejected = sorted(k for k in output if k in FORBIDDEN_KEYS)
        clean = {k: v for k, v in output.items() if k not in FORBIDDEN_KEYS}
        for key in rejected:
            self._journal.append(JournalEvent.new("policy_reject", dedup_key=dedup_key,
                                                  payload={"key": key, "value": _short(output[key])}))
        return clean, rejected


def _short(v: object, limit: int = 500) -> str:
    s = repr(v)
    return s if len(s) <= limit else s[:limit] + "..."
