from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from obiwan.core.config import Settings

T0 = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def inbox_dir(tmp_path: Path) -> Path:
    d = tmp_path / "inbox"
    d.mkdir()
    return d


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A source root with three overlapping documents, so retrieval has known answers."""
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "zebra.md").write_text("# Zebra migration\n\nZebras migrate across the Serengeti every year.\n", encoding="utf-8", newline="\n")
    (d / "invoice.txt").write_text("Invoice 42 is due on Friday. Approve the invoice before then.\n", encoding="utf-8", newline="\n")
    (d / "notes" ).mkdir()
    (d / "notes" / "plan.md").write_text("Plan\n\nMigrate the zebra photos to the NAS after the invoice is paid.\n", encoding="utf-8", newline="\n")
    (d / "image.png").write_bytes(b"\x89PNG not really")
    return d


@pytest.fixture
def settings(data_dir: Path, inbox_dir: Path, corpus: Path) -> Settings:
    return Settings(_env_file=None, data_dir=data_dir, inbox_dir=inbox_dir, source_roots=f"corpus={corpus}",
                    reader_token="r-token", writer_token="w-token", commander_token="c-token", chunk_chars=200)
