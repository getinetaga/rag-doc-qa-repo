"""Document ingestion utilities.

This module provides helpers to extract plain text from common document
formats used by the demo: PDF, DOCX, and plain text files. The functions
here perform basic validation, handle common encoding issues for text
files, and aim to return a cleaned Unicode string suitable for downstream
chunking and embedding.
"""

from pathlib import Path
from typing import Optional
import logging

import pdfplumber
import docx

logger = logging.getLogger(__name__)


def extract_text(file_path: str) -> str:
    """Extract text from a supported file.

    Supported formats: .pdf, .docx, .txt

    Args:
        file_path: Path to the file to extract.

    Returns:
        A Unicode string containing the extracted text. May be empty for
        files that contain no extractable text.

    Raises:
        FileNotFoundError: if `file_path` does not exist.
        ValueError: if the file extension is unsupported.
        Exception: for other I/O or parsing errors (propagated).
    """

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
# Determine file type by extension and call the appropriate extractor
    suffix = path.suffix.lower()
    if suffix == ".pdf":# pdfplumber can handle many PDFs but may fail on scanned/image-based ones
        return extract_pdf(path)
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".txt":
        return extract_txt(path)
# If we reach here, the file type is unsupported
    raise ValueError(f"Unsupported file type: {suffix}")


def extract_pdf(path: Path) -> str:
    """Extract text from a PDF file using pdfplumber.

    This function concatenates page text, skipping pages where no text
    can be extracted (pdfplumber may return None for some pages).
    """

    text_chunks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_chunks.append(page_text)

    return "\n\n".join(text_chunks)


def extract_docx(path: Path) -> str:
    """Extract text from a DOCX file using python-docx.

    Returns the document text with paragraph breaks preserved.
    """

    doc = docx.Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text]
    return "\n\n".join(paragraphs)


def extract_txt(path: Path, encodings: Optional[list] = None) -> str:
    """Read a plain-text file with fallback encodings.

    Tries UTF-8 first, then falls back to a list of provided encodings
    (defaults to Latin-1) to handle text files with different encodings.
    """

    if encodings is None:
        encodings = ["utf-8", "latin-1"]

    last_exc = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError as e:
            last_exc = e
            logger.debug("Decoding %s with %s failed: %s", path, enc, e)
            continue

    # If all decodes fail, re-raise the last error for visibility
    if last_exc:
        raise last_exc
    return ""
 # The above functions can be extended to support more formats (e.g., .xlsx, .pptx)