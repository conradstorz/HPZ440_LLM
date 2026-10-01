"""OpenAI-compatible surface so Open WebUI can list and chat with the Jarvis model."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

MODEL_ID = "jarvis"
Responder = Callable[[list[dict], str | None], Iterator[str]]


def _validate(body: object) -> list[dict]:
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list) or not body["messages"]:
        raise HTTPException(400, "messages must be a non-empty list")
    for m in body["messages"]:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant", "tool") or "content" not in m:
            raise HTTPException(400, "each message needs a role and content")
    return body["messages"]


def _safe(respond: Responder, messages: list[dict], cid: str | None) -> Iterator[str]:
    try:
        yield from respond(messages, cid)
    except Exception as e:  # noqa: BLE001 - model-side problems are reported as a reply, never a 500
        yield f"Jarvis hit an internal error: {type(e).__name__}: {e}"


def openai_router(respond: Responder) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/models")
    def models() -> JSONResponse:
        return JSONResponse({"object": "list", "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "jarvis"}]})

    @router.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "body must be JSON")
        messages = _validate(body)
        cid = body.get("chat_id") or request.headers.get("x-openwebui-chat-id") or None
        rid, created = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time())
        pieces = _safe(respond, messages, cid)
        if not body.get("stream"):
            # The responder is synchronous and slow (model calls, tool calls): draining it on the event loop
            # would stall every other request for the whole turn.
            text = await run_in_threadpool(lambda: "".join(pieces))
            return JSONResponse({"id": rid, "object": "chat.completion", "created": created, "model": MODEL_ID,
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})

        def chunk(delta: dict, finish: str | None = None) -> str:
            return "data: " + json.dumps({"id": rid, "object": "chat.completion.chunk", "created": created, "model": MODEL_ID,
                                          "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"

        def gen() -> Iterator[str]:
            yield chunk({"role": "assistant", "content": ""})
            for piece in pieces:
                yield chunk({"content": piece})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
