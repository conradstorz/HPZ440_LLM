"""Wire the units. The only place a Service is assembled for production."""

from __future__ import annotations

from obiwan.auth import Gate
from obiwan.core.config import Settings
from obiwan.inbox import Inbox
from obiwan.projection import FtsProjection
from obiwan.record import Record
from obiwan.service import Service
from obiwan.work import WorkQueue


def build_service(settings: Settings | None = None) -> Service:
    s = settings or Settings()
    s.roots  # fail at startup, not on the first scan, if OBIWAN_SOURCE_ROOTS is malformed
    record = Record(s.record_path)
    return Service(s, record=record, work=WorkQueue(record), projection=FtsProjection(s.index_dir, record),
                   inbox=Inbox(s.inbox_dir), gate=Gate(record, s))
