from pathlib import Path

import pytest

from obiwan.extract import ExtractionError, extract_text, is_supported, media_type_for


def test_supported_suffixes_and_media_types():
    assert is_supported(Path("a.md")) and is_supported(Path("A.PDF")) and is_supported(Path("x.txt"))
    assert not is_supported(Path("a.png")) and not is_supported(Path("a")) and not is_supported(Path("a.docx"))
    assert media_type_for(Path("a.md")) == "text/markdown"
    assert media_type_for(Path("a.txt")) == "text/plain"
    assert media_type_for(Path("a.pdf")) == "application/pdf"
    assert media_type_for(Path("a.json")) == "application/json"
    assert media_type_for(Path("a.bin")) == "application/octet-stream"


def test_text_files_extract_byte_for_byte(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# Title\n\nBody with ünïcödé.\n", encoding="utf-8", newline="\n")
    assert extract_text(p, max_pdf_pages=5) == "# Title\n\nBody with ünïcödé.\n"
    assert extract_text(p, max_pdf_pages=5) == extract_text(p, max_pdf_pages=5)


def test_invalid_utf8_is_replaced_not_fatal(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"ok \xff\xfe bad")
    assert extract_text(p, max_pdf_pages=5) == "ok �� bad"


def test_empty_text_is_an_extraction_error(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("   \n", encoding="utf-8")
    with pytest.raises(ExtractionError, match="no text"):
        extract_text(p, max_pdf_pages=5)


def test_a_corrupt_pdf_is_an_extraction_error(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(ExtractionError):
        extract_text(p, max_pdf_pages=5)


def test_unsupported_suffix_is_an_extraction_error(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG")
    with pytest.raises(ExtractionError, match="unsupported"):
        extract_text(p, max_pdf_pages=5)


def test_a_real_pdf_extracts_text(tmp_path):
    from pypdf import PdfWriter

    p = tmp_path / "real.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_metadata({"/Title": "t"})
    with p.open("wb") as f:
        w.write(f)
    # A blank page has no text: that is "no text", not a crash.
    with pytest.raises(ExtractionError, match="no text"):
        extract_text(p, max_pdf_pages=5)
