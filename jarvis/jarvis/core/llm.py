"""LLM client contract. The real client talks to llama.cpp's OpenAI-compatible endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field


class LLMError(Exception):
    pass


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class ChatTurn(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str = "stop"


class LLMClient(Protocol):
    model_name: str

    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int = 1024) -> dict: ...
    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, max_tokens: int = 1024) -> ChatTurn: ...
    def chat_stream(self, messages: list[dict], *, max_tokens: int = 1024) -> Iterator[str]: ...


def _parse_tool_calls(raw: list | None) -> list[ToolCall]:
    out: list[ToolCall] = []
    for i, tc in enumerate(raw or []):
        fn = (tc or {}).get("function") or {}
        args_text = fn.get("arguments")
        if isinstance(args_text, dict):
            args: dict = args_text
        else:
            try:
                parsed = json.loads(args_text or "{}")
                args = parsed if isinstance(parsed, dict) else {"_raw": args_text}
            except (TypeError, ValueError):
                args = {"_raw": str(args_text)}
        out.append(ToolCall(id=tc.get("id") or f"call_{i}", name=str(fn.get("name") or ""), arguments=args))
    return out


class LlamaCppClient:
    def __init__(self, base_url: str, model_name: str, timeout: float = 120.0, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int = 1024) -> dict:
        body = {
            "model": self.model_name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}},
        }
        try:
            resp = self._client.post(f"{self.base_url}/v1/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise LLMError(f"HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise LLMError(str(e)) from e
        try:
            choice = resp.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise LLMError("model output truncated at max_tokens")
            content = choice["message"]["content"]
            out = json.loads(content)
        # TypeError/AttributeError cover a 200 whose shape is wrong rather than merely absent: a null content,
        # a choice that is not a mapping. Every one becomes an LLMError so the caller's retry path applies.
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        if not isinstance(out, dict):
            raise LLMError("model returned non-object JSON")
        return out

    def is_reachable(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/v1/models", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def _post(self, body: dict) -> httpx.Response:
        try:
            resp = self._client.post(f"{self.base_url}/v1/chat/completions", json=body)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            raise LLMError(f"HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise LLMError(str(e)) from e

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, max_tokens: int = 1024) -> ChatTurn:
        body: dict[str, Any] = {"model": self.model_name, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        resp = self._post(body)
        try:
            choice = resp.json()["choices"][0]
            msg = choice["message"]
            return ChatTurn(content=msg.get("content"), tool_calls=_parse_tool_calls(msg.get("tool_calls")),
                            finish_reason=choice.get("finish_reason") or "stop")
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e

    def chat_stream(self, messages: list[dict], *, max_tokens: int = 1024) -> Iterator[str]:
        body = {"model": self.model_name, "messages": messages, "temperature": 0, "max_tokens": max_tokens, "stream": True}
        try:
            with self._client.stream("POST", f"{self.base_url}/v1/chat/completions", json=body) as resp:
                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.read()[:300]!r}")
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        delta = json.loads(data)["choices"][0].get("delta") or {}
                    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as e:
                        raise LLMError(f"bad stream chunk: {e}") from e
                    if delta.get("content"):
                        yield delta["content"]
        except httpx.HTTPError as e:
            raise LLMError(str(e)) from e


class FakeLLM:
    """Queued responses in order. An Exception instance in a queue is raised when reached."""

    def __init__(self, responses: list[Any] | None = None, model_name: str = "fake", *,
                 turns: list[Any] | None = None, stream_chunks: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.turns = list(turns or [])
        self.stream_chunks = list(stream_chunks or [])
        self.model_name = model_name
        self.calls: list[dict] = []
        self.chat_calls: list[dict] = []

    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int = 1024) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self.responses:
            raise LLMError("FakeLLM has no queued response")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, max_tokens: int = 1024) -> ChatTurn:
        self.chat_calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.turns:
            raise LLMError("FakeLLM has no queued turn")
        t = self.turns.pop(0)
        if isinstance(t, Exception):
            raise t
        return t

    def chat_stream(self, messages: list[dict], *, max_tokens: int = 1024) -> Iterator[str]:
        self.chat_calls.append({"messages": [dict(m) for m in messages], "tools": None, "stream": True})
        yield from self.stream_chunks
