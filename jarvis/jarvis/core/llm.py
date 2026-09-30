"""LLM client contract. The real client talks to llama.cpp's OpenAI-compatible endpoint."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    model_name: str

    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int = 1024) -> dict: ...


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
            content = resp.json()["choices"][0]["message"]["content"]
            out = json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LLMError(str(e)) from e
        if not isinstance(out, dict):
            raise LLMError("model returned non-object JSON")
        return out

    def is_reachable(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/v1/models", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False


class FakeLLM:
    """Returns queued responses in order. An Exception instance in the queue is raised."""

    def __init__(self, responses: list[Any] | None = None, model_name: str = "fake") -> None:
        self.responses = list(responses or [])
        self.model_name = model_name
        self.calls: list[dict] = []

    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int = 1024) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self.responses:
            raise LLMError("FakeLLM has no queued response")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
