"""Text chunking utilities for retrieval.

This module splits raw document text into overlapping fixed-size chunks
using character counts. Overlap helps preserve context between adjacent
chunks so retrieval remains coherent near chunk boundaries.
"""

from .config import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_text(text: str) -> list[str]:
    """Split input text into overlapping chunks.

    Args:
        text: Full document text to split.

    Returns:
        A list of string chunks where each chunk has at most
        ``CHUNK_SIZE`` characters and consecutive chunks overlap by
        ``CHUNK_OVERLAP`` characters.

    Raises:
        ValueError: If ``CHUNK_OVERLAP`` is greater than or equal to
            ``CHUNK_SIZE``.
    """
    if CHUNK_OVERLAP >= CHUNK_SIZE:
        raise ValueError("CHUNK_OVERLAP must be less than CHUNK_SIZE")
    chunks = []
    start = 0

    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - CHUNK_OVERLAP

    return chunks
