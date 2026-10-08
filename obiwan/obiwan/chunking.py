"""Deterministic chunking by character position. A chunk is a span of the source text; nothing is rewritten."""

from __future__ import annotations

import re
from dataclasses import dataclass

_PARA = re.compile(r"\n[ \t]*\n+")


@dataclass(frozen=True)
class ChunkSpec:
    seq: int
    start_char: int
    end_char: int
    text: str


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _PARA.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    out = []
    for s, e in spans:
        seg = text[s:e]
        if not seg.strip():
            continue
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg) - len(seg.rstrip())
        out.append((s + lead, e - trail))
    return out


def _split_long(text: str, s: int, e: int, limit: int) -> list[tuple[int, int]]:
    pieces = []
    pos = s
    while pos < e:
        cut = min(pos + limit, e)
        if cut < e:
            ws = text.rfind(" ", pos + limit // 2, cut)
            if ws > pos:
                cut = ws
        pieces.append((pos, cut))
        pos = cut
        while pos < e and text[pos] == " ":
            pos += 1
    return pieces


def chunk_text(text: str, *, chunk_chars: int = 1500) -> list[ChunkSpec]:
    if chunk_chars < 1:
        raise ValueError("chunk_chars must be positive")
    pieces: list[tuple[int, int]] = []
    for s, e in _paragraph_spans(text):
        if e - s <= chunk_chars:
            pieces.append((s, e))
        else:
            pieces.extend(_split_long(text, s, e, chunk_chars))
    merged: list[tuple[int, int]] = []
    for s, e in pieces:
        if merged and e - merged[-1][0] <= chunk_chars:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [ChunkSpec(i, s, e, text[s:e]) for i, (s, e) in enumerate(merged)]
