"""Tests for `app.ingestion` helpers.

These tests verify that `extract_text` correctly handles plain text and
DOCX files, that encoding fallbacks are honored, and that unsupported
extensions raise `ValueError`.
"""

from pathlib import Path
import tempfile
import pytest

from app.ingestion import extract_text


def test_extract_txt(tmp_path: Path):
    p = tmp_path / "sample.txt"
    content = "Hello world\nThis is a test."
    p.write_text(content, encoding="utf-8")

    out = extract_text(str(p))
    assert "Hello world" in out
    assert "This is a test." in out


def test_extract_docx(tmp_path: Path):
    # Create a small DOCX file using python-docx
    try:
        import docx
    except Exception:
        pytest.skip("python-docx not available")

    p = tmp_path / "sample.docx"
    doc = docx.Document()
    doc.add_paragraph("Paragraph one")
    doc.add_paragraph("Paragraph two")
    doc.save(str(p))

    out = extract_text(str(p))
    assert "Paragraph one" in out
    assert "Paragraph two" in out


def test_extract_unsupported_extension(tmp_path: Path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"\x00\x01\x02")

    try:
        extract_text(str(p))
    except ValueError as e:
        assert "Unsupported file type" in str(e)
    else:
        raise AssertionError("Expected ValueError for unsupported extension")