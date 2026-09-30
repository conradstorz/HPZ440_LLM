"""Versioned archive: <data>/archive/<key>/nko-v<N>.json plus raw files. The source of truth."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from jarvis.core.nko import NKO

_VERSION_FILE = re.compile(r"^nko-v(\d+)\.json$")


class VersionExists(Exception):
    pass


def key_to_dirname(dedup_key: str) -> str:
    return dedup_key.replace(":", "_").replace("/", "_")


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.archive = Path(data_dir) / "archive"
        self.archive.mkdir(parents=True, exist_ok=True)

    def _dir(self, dedup_key: str) -> Path:
        return self.archive / key_to_dirname(dedup_key)

    def save_version(self, nko: NKO) -> Path:
        d = self._dir(nko.dedup_key)
        d.mkdir(parents=True, exist_ok=True)
        final = d / f"nko-v{nko.version}.json"
        if final.exists():
            raise VersionExists(f"{nko.dedup_key} v{nko.version} already exists")
        # A unique temp name keeps two concurrent writers from publishing each other's half-written bytes.
        tmp = d / f"nko-v{nko.version}.json.{os.getpid()}-{uuid4().hex[:8]}.tmp"
        try:
            tmp.write_text(nko.model_dump_json(indent=2), encoding="utf-8")
            # os.link is the publish step because it refuses to clobber: os.replace would silently overwrite a
            # version another writer published between the exists() check above and here.
            os.link(tmp, final)
        except FileExistsError as e:
            raise VersionExists(f"{nko.dedup_key} v{nko.version} already exists") from e
        finally:
            tmp.unlink(missing_ok=True)
        return final

    def save_raw(self, dedup_key: str, name: str, data: bytes) -> Path:
        path = self._dir(dedup_key) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return path

    def exists(self, dedup_key: str) -> bool:
        return (self._dir(dedup_key) / "nko-v0.json").exists()

    def _version_files(self, d: Path) -> list[tuple[int, Path]]:
        out = []
        if not d.is_dir():
            return out
        for p in d.iterdir():
            m = _VERSION_FILE.match(p.name)
            if m:
                out.append((int(m.group(1)), p))
        return sorted(out)

    def get_versions(self, dedup_key: str) -> list[NKO]:
        return [NKO.model_validate_json(p.read_text(encoding="utf-8")) for _, p in self._version_files(self._dir(dedup_key))]

    def get_version(self, dedup_key: str, version: int) -> NKO:
        p = self._dir(dedup_key) / f"nko-v{version}.json"
        return NKO.model_validate_json(p.read_text(encoding="utf-8"))

    def get_latest(self, dedup_key: str) -> NKO | None:
        files = self._version_files(self._dir(dedup_key))
        if not files:
            return None
        return NKO.model_validate_json(files[-1][1].read_text(encoding="utf-8"))

    def iter_latest(self) -> Iterator[NKO]:
        for d in sorted(self.archive.iterdir()):
            files = self._version_files(d)
            if files:
                yield NKO.model_validate_json(files[-1][1].read_text(encoding="utf-8"))

    def count(self) -> int:
        """Archived messages, counted from the directory listing only — no JSON is parsed."""
        return sum(1 for d in self.archive.iterdir() if (d / "nko-v0.json").exists())
