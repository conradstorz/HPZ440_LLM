"""Deterministic text extraction. Same bytes in, same text out; anything else raises ExtractionError."""

from __future__ import annotations

import io
import warnings
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".log", ".json", ".yaml", ".yml", ".toml", ".ini"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = frozenset(TEXT_SUFFIXES | PDF_SUFFIXES)
EXTRACTOR = "obiwan.extract/1"  # recorded alongside projections later; bump when extraction output could change

_MEDIA = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain", ".rst": "text/x-rst", ".csv": "text/csv",
          ".log": "text/plain", ".json": "application/json", ".yaml": "application/yaml", ".yml": "application/yaml",
          ".toml": "application/toml", ".ini": "text/plain", ".pdf": "application/pdf"}


class ExtractionError(Exception):
    pass


def is_supported(path: Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def media_type_for(path: Path) -> str:
    return _MEDIA.get(Path(path).suffix.lower(), "application/octet-stream")


def extract_text(path: Path, *, max_pdf_pages: int) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        text = path.read_bytes().decode("utf-8", errors="replace")
    elif suffix in PDF_SUFFIXES:
        text = _pdf_text(path.read_bytes(), max_pdf_pages)
    else:
        raise ExtractionError(f"unsupported file type {suffix!r}")
    if not text.strip():
        raise ExtractionError("no text extracted")
    return text


def _pdf_text(data: bytes, max_pdf_pages: int) -> str:
    from pypdf import PdfReader

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # pypdf warns about malformed structure; the outcome is what matters
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise ExtractionError("encrypted PDF")
            pages = reader.pages[:max_pdf_pages] if max_pdf_pages > 0 else reader.pages
            return "\n".join((page.extract_text() or "") for page in pages)
    except ExtractionError:
        raise
    except Exception as e:  # noqa: BLE001 - every pypdf failure is one extraction failure, recorded with its type
        raise ExtractionError(f"{type(e).__name__}: {e}") from e
