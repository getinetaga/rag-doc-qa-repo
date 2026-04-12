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


def test_extract_pdf_with_mocked_pdfplumber(monkeypatch, tmp_path: Path):
    p = tmp_path / "sample.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake")

    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _PDF:
        def __init__(self):
            self.pages = [_Page("Page 1 text"), _Page(None), _Page("Page 3 text")]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_open(path):
        assert str(path).endswith("sample.pdf")
        return _PDF()

    monkeypatch.setattr("app.ingestion.pdfplumber.open", fake_open)

    out = extract_text(str(p))
    assert "Page 1 text" in out
    assert "Page 3 text" in out
    assert "None" not in out


def test_extract_txt_latin1_fallback(tmp_path: Path):
    p = tmp_path / "latin1.txt"
    p.write_bytes("cafe\xe9".encode("latin-1"))

    out = extract_text(str(p))
    assert out == "cafeé"


def test_extract_missing_file_raises_file_not_found(tmp_path: Path):
    missing = tmp_path / "does_not_exist.txt"
    with pytest.raises(FileNotFoundError):
        extract_text(str(missing))