"""Path containment: nothing read from a source root or the inbox may resolve outside it."""

from __future__ import annotations

from pathlib import Path


class PathEscapesRoot(Exception):
    """A read was refused because the path resolves outside its root (or the inbox)."""


def is_contained(path: Path, root: Path) -> bool:
    """True if ``path`` resolves to ``root`` or somewhere beneath it, following symlinks and ``..``.
    A path that cannot be resolved (loop, permission, bad name) is not contained."""
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, RuntimeError, ValueError):
        return False
