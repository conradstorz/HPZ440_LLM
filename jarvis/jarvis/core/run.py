from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RunSummary(BaseModel):
    since: datetime
    captured: int = 0
    classified: int = 0
    drafted: int = 0
    errors: int = 0
    skipped: int = 0
    capped: bool = False  # the per-run cap stopped polling; more messages are waiting for the next run
    poll_failed: bool = False  # a source's poll() raised; the window was not fully listed
