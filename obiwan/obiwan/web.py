"""FastAPI surface (mvp.md section 14). Published on the host loopback only; the LAN reaches it through Jarvis."""

from __future__ import annotations

import threading
from typing import Any, Literal

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from obiwan.auth import Refused
from obiwan.service import Service


class SubmitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    title: str | None = None


class RelayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    conversation_ref: str
    title: str | None = None


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: str
    action: Literal["promote", "forget"] = "promote"
    reason: str | None = None


def _parse(model, body: dict):
    try:
        return model.model_validate(body)
    except ValidationError as e:
        raise HTTPException(400, e.errors(include_url=False, include_input=False)) from e


def _object(body: Any) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    return body


def create_app(service: Service) -> FastAPI:
    app = FastAPI(title="Obi-Wan", docs_url=None, redoc_url=None)
    app.state.scan_lock = threading.Lock()

    def guard(power: str):
        def dep(authorization: str | None = Header(default=None)) -> str:
            try:
                return service.gate.authorize(authorization, power)
            except Refused as e:
                raise HTTPException(e.status, e.reason) from e
        return dep

    def checked(body: dict, *, role: str, route: str) -> None:
        try:
            service.gate.refuse_claimed_provenance(body, role=role, route=route)
        except Refused as e:
            raise HTTPException(e.status, e.reason) from e

    @app.get("/health")
    def health() -> JSONResponse:
        cov = service.coverage()
        return JSONResponse({"ok": True, "documents": cov["documents"], "last_scan_at": cov["last_scan_at"]})

    @app.get("/search")
    def search(q: str = "", k: int = 8, role: str = Depends(guard("search"))) -> dict:
        return service.search(q, k)

    @app.get("/document/{doc_id}")
    def document(doc_id: str, role: str = Depends(guard("read_document"))) -> dict:
        view = service.document(doc_id)
        if view is None:
            raise HTTPException(404, "unknown document")
        return view

    @app.get("/status")
    def status(role: str = Depends(guard("status"))) -> dict:
        return service.status()

    @app.get("/journal")
    def journal(limit: int = 50, role: str = Depends(guard("journal_read"))) -> list[dict]:
        return service.journal(limit=max(1, min(limit, 500)))

    @app.post("/submit")
    def submit(body: Any = Body(default_factory=dict), role: str = Depends(guard("submit"))) -> dict:
        body = _object(body)
        checked(body, role=role, route="submit")
        p = _parse(SubmitBody, body)
        try:
            return service.submit(content=p.content, title=p.title, role=role)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/relay")
    def relay(body: Any = Body(default_factory=dict), role: str = Depends(guard("relay"))) -> dict:
        body = _object(body)
        checked(body, role=role, route="relay")
        p = _parse(RelayBody, body)
        try:
            return service.relay(content=p.content, conversation_ref=p.conversation_ref, title=p.title, role=role)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/confirm")
    def confirm(body: Any = Body(default_factory=dict), role: str = Depends(guard("confirm")),
                authorization: str | None = Header(default=None)) -> dict:
        body = _object(body)
        checked(body, role=role, route="confirm")
        p = _parse(ConfirmBody, body)
        try:
            if p.action == "forget":
                guard("forget")(authorization)
                if not (p.reason or "").strip():
                    raise HTTPException(400, "reason is required to forget")
                return service.forget(subject_id=p.subject_id, reason=p.reason, role=role)
            return service.confirm(subject_id=p.subject_id, role=role)
        except KeyError as e:
            raise HTTPException(404, f"unknown subject {p.subject_id}") from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/scan")
    def scan(role: str = Depends(guard("scan"))) -> dict:
        lock = app.state.scan_lock
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "a scan is already in progress")
        try:
            return service.scan(role=role)
        finally:
            lock.release()

    @app.post("/reindex")
    def reindex(role: str = Depends(guard("reindex"))) -> dict:
        return service.reindex(role=role)

    return app


def app_factory() -> FastAPI:
    """Production entry point (uvicorn --factory)."""
    from obiwan.runtime import build_service

    return create_app(build_service())
