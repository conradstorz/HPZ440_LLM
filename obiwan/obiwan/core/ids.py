"""Identity and time helpers. file_id and doc_id are minted here and nowhere else."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def sha256_file(path: Path, *, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
