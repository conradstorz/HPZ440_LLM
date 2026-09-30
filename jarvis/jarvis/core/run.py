from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RunSummary(BaseModel):
    since: datetime
    captured: int = 0
    classified: int = 0
    drafted: int = 0
    errors: int = 0
