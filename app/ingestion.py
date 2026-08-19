"""Document ingestion utilities.

This module provides helpers to extract plain text from common document
formats used by the demo: PDF, DOCX, TXT, image files, and Google Docs.
The functions perform basic validation and return Unicode text suitable
for downstream chunking and embedding.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import docx
import pdfplumber
import requests

logger = logging.getLogger(__name__)


def extract_text(file_path: str) -> str:
    """Extract text from a supported file.

    Supported formats: .pdf, .docx, .txt, image files (.png/.jpg/...)

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
    logger.info("Extracting text from '%s'", path.name)
    _t0 = time.monotonic()

    # Determine file type by extension and call the appropriate extractor.
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        result = extract_pdf(path)
    elif suffix == ".docx":
        result = extract_docx(path)
    elif suffix == ".txt":
        result = extract_txt(path)
    elif suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}:
        result = extract_image(path)
    else:
        # If we reach here, the file type is unsupported.
        raise ValueError(f"Unsupported file type: {suffix}")

    logger.info(
        "Extraction complete: '%s' — %d chars in %.2fs",
        path.name, len(result), time.monotonic() - _t0,
    )
    return result


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


def extract_image(path: Path) -> str:
    """Extract text from an image file using OCR.

    Requires Pillow and pytesseract at runtime. If they are missing,
    a clear error is raised so callers know how to enable image support.
    """

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for image ingestion. Install `Pillow`.") from exc

    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("pytesseract is required for image OCR. Install `pytesseract`.") from exc

    with Image.open(path) as img:
        # RGB normalization improves OCR consistency across image formats.
        text = pytesseract.image_to_string(img.convert("RGB"))
    return text.strip()


def extract_google_doc_text(google_doc_url: str, timeout_seconds: int = 20) -> str:
    """Fetch plain text content from a Google Docs URL.

    Supports shared documents accessible by URL and exports the document
    as plain text via Google's export endpoint.
    """

    doc_id = _extract_google_doc_id(google_doc_url)
    if not doc_id:
        raise ValueError("Invalid Google Docs URL. Expected a /document/d/<doc_id>/ link.")

    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    try:
        response = requests.get(export_url, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch Google Doc content: {exc}") from exc

    text = response.text.strip()
    if not text:
        raise ValueError("Google Doc returned empty content or is not accessible.")
    return text


def _extract_google_doc_id(google_doc_url: str) -> str | None:
    """Extract a Google Docs document ID from a URL."""

    parsed = urlparse(google_doc_url)
    if "docs.google.com" not in parsed.netloc:
        return None

    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)

    query_doc_id = parse_qs(parsed.query).get("id", [])
    if query_doc_id:
        return query_doc_id[0]

    return None