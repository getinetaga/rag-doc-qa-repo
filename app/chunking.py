"""Text chunking utilities for retrieval.

This module splits raw document text into overlapping fixed-size chunks
using character counts. Overlap helps preserve context between adjacent
chunks so retrieval remains coherent near chunk boundaries, and each chunk
is labeled with a section reference so answers can cite where they came from.
"""

import re

from .config import CHUNK_SIZE, CHUNK_OVERLAP

_SECTION_HINT_RE = re.compile(r"^(section|chapter|part|appendix)\b", re.IGNORECASE)
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*[\)\].:-]?\s+.+$")


def _infer_section_label(chunk: str, index: int) -> str:
    """Infer a human-readable section label for a chunk.

    Preference order:
    1. A short heading-like line near the top of the chunk.
    2. A fallback label like ``Section 1`` when no heading is found.
    """

    lines = [" ".join(line.split()) for line in chunk.splitlines() if line.strip()]
    for line in lines[:5]:
        candidate = line[:80].rstrip(":")
        if not candidate:
            continue
        looks_like_heading = len(candidate) <= 80 and (
            _SECTION_HINT_RE.match(candidate)
            or _NUMBERED_HEADING_RE.match(candidate)
            or candidate.isupper()
            or candidate.istitle()
        )
        if looks_like_heading:
            return candidate

    return f"Section {index + 1}"


def chunk_text(text: str) -> list[str]:
    """Split input text into overlapping, section-labeled chunks.

    Args:
        text: Full document text to split.

    Returns:
        A list of string chunks where each chunk has at most
        ``CHUNK_SIZE`` characters and consecutive chunks overlap by
        ``CHUNK_OVERLAP`` characters. Each chunk is prefixed with a
        bracketed section label such as ``[Section 1]`` or a detected
        heading name to support answer citations.

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
        chunk = text[start:end].strip()
        if chunk:
            label = _infer_section_label(chunk, len(chunks))
            chunks.append(f"[{label}] {chunk}")
        start = end - CHUNK_OVERLAP

    return chunks
