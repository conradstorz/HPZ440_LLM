"""FastAPI surface: briefing, corrections, run trigger, message history, health. LAN only, no auth."""

from __future__ import annotations

import threading
from collections.abc import Callable

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from jarvis.briefing import Briefing
from jarvis.core.run import RunSummary
from jarvis.core.store import Store
from jarvis.journal import Journal


def create_app(*, store: Store, journal: Journal, briefing: Briefing, run: Callable[[], RunSummary],
               llm_reachable: Callable[[], bool]) -> FastAPI:
    app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None)
    run_lock = threading.Lock()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        nkos = list(store.iter_latest())
        errors = {}
        for n in nkos:
            if not n.classifications:
                e = journal.last_error_for(n.dedup_key)
                if e:
                    errors[n.dedup_key] = e
        return briefing.render(nkos, errors)

    @app.post("/correct")
    def correct(dedup_key: str = Form(...), to_group: str = Form(...), note: str = Form("")) -> RedirectResponse:
        try:
            briefing.apply_correction(dedup_key, to_group, note.strip() or None)
        except KeyError:
            raise HTTPException(404, "unknown message")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return RedirectResponse("/", status_code=303)

    @app.post("/run")
    def trigger_run() -> RedirectResponse:
        if not run_lock.acquire(blocking=False):
            raise HTTPException(409, "a run is already in progress")
        try:
            run()
        finally:
            run_lock.release()
        return RedirectResponse("/", status_code=303)

    @app.get("/message/{dedup_key}", response_class=HTMLResponse)
    def message(dedup_key: str) -> str:
        versions = store.get_versions(dedup_key)
        if not versions:
            raise HTTPException(404, "unknown message")
        return briefing.render_message(versions[-1], versions, journal.events_for(dedup_key))

    @app.get("/health")
    def health() -> JSONResponse:
        last = journal.last_run()
        return JSONResponse({"ok": True, "llm": bool(llm_reachable()), "messages": store.count(),
                             "last_run": last.ts.isoformat() if last else None})

    return app


def app_factory() -> FastAPI:
    """Production entry point (uvicorn --factory). Completed in the pipeline task."""
    from jarvis.pipeline import build_runtime

    rt = build_runtime()
    return create_app(store=rt.store, journal=rt.journal, briefing=rt.briefing, run=rt.run_once,
                      llm_reachable=rt.llm.is_reachable)
