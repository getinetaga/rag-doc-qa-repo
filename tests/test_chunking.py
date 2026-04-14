"""Unit tests for chunking behavior and section labeling."""

from app import chunking


def test_chunk_text_uses_heading_as_section_label(monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_SIZE", 120)
    monkeypatch.setattr(chunking, "CHUNK_OVERLAP", 10)

    text = "Introduction\nThis is the opening section of the document."

    chunks = chunking.chunk_text(text)

    assert len(chunks) == 1
    assert chunks[0].startswith("[Introduction]")


def test_chunk_text_falls_back_to_numbered_sections(monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_SIZE", 12)
    monkeypatch.setattr(chunking, "CHUNK_OVERLAP", 2)

    chunks = chunking.chunk_text("abcdefghijklmnopqrstuvwxyz")

    assert len(chunks) >= 2
    assert chunks[0].startswith("[Section 1]")
    assert chunks[1].startswith("[Section 2]")


def test_chunk_text_detects_numbered_heading(monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_SIZE", 120)
    monkeypatch.setattr(chunking, "CHUNK_OVERLAP", 10)

    text = "1. Overview\nThe numbered heading should be used as the label."

    chunks = chunking.chunk_text(text)

    assert chunks[0].startswith("[1. Overview]")


def test_chunk_text_rejects_invalid_overlap(monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_SIZE", 50)
    monkeypatch.setattr(chunking, "CHUNK_OVERLAP", 50)

    try:
        chunking.chunk_text("sample text")
    except ValueError as exc:
        assert "CHUNK_OVERLAP must be less than CHUNK_SIZE" in str(exc)
    else:
        raise AssertionError("Expected ValueError when overlap is not smaller than chunk size")