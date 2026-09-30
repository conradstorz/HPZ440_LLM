"""Tool registry: every tool has a JSON schema, a policy action, and a handler. run() is the only path a model call takes."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict

from jarvis.core.llm import ToolCall
from jarvis.journal import Journal, JournalEvent
from jarvis.policy import Policy, PolicyViolation

TRUNCATED = " [truncated]"


class Tool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    parameters: dict
    action: str
    handler: Callable[..., str]
    result_chars: int = 4000
    # Opt-in: the handler takes a `_context` keyword carrying facts the model must not be able to forge,
    # such as whether the current user message authorises an explicit note.
    wants_context: bool = False


class ToolRegistry:
    def __init__(self, policy: Policy, journal: Journal, tools: Iterable[Tool] = ()) -> None:
        self._policy, self._journal = policy, journal
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self.register(t)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in self._tools.values()]

    def run(self, call: ToolCall, *, conversation_id: str | None = None, context: dict | None = None) -> str:
        tool = self._tools.get(call.name)
        if tool is None or "_raw" in call.arguments:
            problem = f"unknown tool '{call.name}'" if tool is None else "invalid tool arguments"
            self._journal.append(JournalEvent.new("policy_reject", payload={"key": call.name, "value": repr(call.arguments)[:500],
                                                                            "conversation_id": conversation_id}))
            return f"error: {problem}"
        try:
            # Outside the handler's try: a blocked action is a gate decision, not a tool failure, so it is
            # journaled as policy_reject and never as a tool_call.
            self._policy.check(tool.action)
        except PolicyViolation as e:
            self._journal.append(JournalEvent.new("policy_reject", payload={"key": tool.name, "value": tool.action,
                                                                            "conversation_id": conversation_id}))
            return f"error: PolicyViolation: {e}"
        kwargs = dict(call.arguments)
        if tool.wants_context:
            kwargs["_context"] = context or {}
        ok, result = True, ""
        try:
            result = str(tool.handler(**kwargs))
        except Exception as e:  # noqa: BLE001 - the model sees the error text and can recover
            ok, result = False, f"error: {type(e).__name__}: {e}"
        if ok and len(result) > tool.result_chars:  # error strings are short and must stay whole so the model sees the type
            result = result[: tool.result_chars] + TRUNCATED
        self._journal.append(JournalEvent.new("tool_call", payload={"name": tool.name, "arguments": call.arguments, "ok": ok,
                                                                    "summary": result[:200], "conversation_id": conversation_id}))
        return result
