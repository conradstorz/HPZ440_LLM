"""FastAPI surface: briefing, corrections, run trigger, message history, notes, chat, health. LAN only, no auth."""

from __future__ import annotations

import threading
from collections.abc import Callable

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from jarvis.briefing import Briefing
from jarvis.core.nko import effective_group
from jarvis.core.run import RunSummary
from jarvis.core.store import Store
from jarvis.journal import Journal, JournalEvent
from jarvis.notes import Notes
from jarvis.openai_api import Responder, openai_router


def create_app(*, store: Store, journal: Journal, briefing: Briefing, run: Callable[[], RunSummary],
               llm_reachable: Callable[[], bool], notes: Notes | None = None,
               respond: Responder | None = None) -> FastAPI:
    app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None)
    run_lock = threading.Lock()
    if respond is not None:
        app.include_router(openai_router(respond))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        nkos = list(store.iter_latest())
        errors = {}
        for n in nkos:
            if effective_group(n) is None:  # same bucketing Briefing.render uses
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
        except Exception as e:  # noqa: BLE001 - the operator needs the reason, not a bare 500
            detail = f"{type(e).__name__}: {e}"
            journal.append(JournalEvent.new("error", payload={"stage": "run", "message": detail[:1000]}))
            raise HTTPException(500, detail) from e
        finally:
            run_lock.release()
        return RedirectResponse("/", status_code=303)

    @app.get("/message/{dedup_key}", response_class=HTMLResponse)
    def message(dedup_key: str) -> str:
        versions = store.get_versions(dedup_key)
        if not versions:
            raise HTTPException(404, "unknown message")
        return briefing.render_message(versions[-1], versions, journal.events_for(dedup_key))

    if notes is not None:
        @app.get("/notes", response_class=HTMLResponse)
        def notes_page() -> str:
            return briefing.render_notes(notes.all_latest())

        @app.post("/notes/retire")
        def retire_note(note_id: str = Form(...), reason: str = Form(...)) -> RedirectResponse:
            try:
                notes.retire(note_id, reason.strip() or "retired from the notes page")
            except KeyError:
                raise HTTPException(404, "unknown note")
            except ValueError as e:
                raise HTTPException(400, str(e))
            return RedirectResponse("/notes", status_code=303)

        @app.post("/notes/retire-pending")
        def retire_pending(reason: str = Form("retired in bulk")) -> RedirectResponse:
            notes.retire_all_pending(reason.strip() or "retired in bulk")
            return RedirectResponse("/notes", status_code=303)

    @app.get("/health")
    def health() -> JSONResponse:
        last = journal.last_run()
        return JSONResponse({"ok": True, "llm": bool(llm_reachable()), "messages": store.count(),
                             "last_run": last.ts.isoformat() if last else None})

    return app


def app_factory() -> FastAPI:
    """Production entry point (uvicorn --factory)."""
    from jarvis.pipeline import build_runtime

    rt = build_runtime()
    return create_app(store=rt.store, journal=rt.journal, briefing=rt.briefing, run=rt.run_once,
                      llm_reachable=rt.llm.is_reachable, notes=rt.notes, respond=rt.respond)
