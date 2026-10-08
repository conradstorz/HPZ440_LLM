"""Settings. Every value comes from an OBIWAN_* environment variable set in compose.yaml."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RESERVED_ROOT = "inbox"  # the inbox is recorded under this root name; a source root may not take it


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBIWAN_")

    data_dir: Path = Path("/data")
    inbox_dir: Path = Path("/inbox")
    # "name=/container/path;name2=/path2". The name is the stable identity recorded in sightings; the path is
    # where the root is mounted today and may change without touching the record.
    source_roots: str = ""
    reader_token: str = ""
    writer_token: str = ""
    commander_token: str = ""
    chunk_chars: int = 1500
    max_file_bytes: int = 20_000_000
    max_pdf_pages: int = 200
    max_submit_chars: int = 20_000
    max_attempts: int = 5
    lease_seconds: int = 300
    search_k_max: int = 25

    @property
    def roots(self) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for part in (p.strip() for p in self.source_roots.split(";")):
            if not part:
                continue
            name, sep, path = part.partition("=")
            name, path = name.strip(), path.strip()
            if not sep or not name or not path:
                raise ValueError(f"OBIWAN_SOURCE_ROOTS entry {part!r} must be name=path")
            if name == RESERVED_ROOT:
                raise ValueError(f"root name {RESERVED_ROOT!r} is reserved for the inbox")
            out[name] = Path(path)
        return out

    @property
    def record_path(self) -> Path:
        return self.data_dir / "record.sqlite"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"
