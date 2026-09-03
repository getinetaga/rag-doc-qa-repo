"""Document ingestion utilities.

This module provides helpers to extract plain text from common document
formats used by the demo: PDF, DOCX, TXT, image files, Google Docs, and
SharePoint / OneDrive-for-Business files (via Microsoft Graph). The functions
perform basic validation and return Unicode text suitable for downstream
chunking and embedding.
"""

import base64
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import docx
import pdfplumber
import requests

from . import config

logger = logging.getLogger(__name__)

# Extensions handled by `extract_text`. Kept as a single source of truth so
# callers that fetch a remote file (Google Docs, SharePoint) can validate the
# file type before downloading.
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}
_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"} | _IMAGE_SUFFIXES


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
    elif suffix in _IMAGE_SUFFIXES:
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


# ---------------------------------------------------------------------------
# SharePoint / Microsoft Graph ingestion
# ---------------------------------------------------------------------------

_GRAPH_TOKEN_LOCK = threading.Lock()
# Cache app-only Graph tokens per client id: {client_id: (expires_at, token)}.
_GRAPH_TOKEN_CACHE: dict[str, tuple[float, str]] = {}


def _reset_graph_token_cache() -> None:
    """Clear the cached Graph token (used by tests and manual invalidation)."""

    with _GRAPH_TOKEN_LOCK:
        _GRAPH_TOKEN_CACHE.clear()


def _get_graph_token(timeout_seconds: int = 30) -> str:
    """Return an app-only Microsoft Graph access token, cached until it expires.

    Uses the OAuth2 client-credentials grant against
    ``<GRAPH_AUTHORITY>/<tenant>/oauth2/v2.0/token`` with the
    ``https://graph.microsoft.com/.default`` scope.

    Raises:
        ValueError: if the SharePoint credentials are not configured.
        requests.HTTPError: for a non-2xx token response.
        RuntimeError: if the token response has no ``access_token``.
    """

    tenant = config.SHAREPOINT_TENANT_ID
    client_id = config.SHAREPOINT_CLIENT_ID
    client_secret = config.SHAREPOINT_CLIENT_SECRET
    if not (tenant and client_id and client_secret):
        raise ValueError(
            "SharePoint ingestion requires SHAREPOINT_TENANT_ID, "
            "SHAREPOINT_CLIENT_ID, and SHAREPOINT_CLIENT_SECRET to be set."
        )

    with _GRAPH_TOKEN_LOCK:
        cached = _GRAPH_TOKEN_CACHE.get(client_id)
        # Refresh a minute early to avoid using a token that expires in flight.
        if cached and cached[0] > time.time() + 60:
            return cached[1]

        token_url = f"{config.GRAPH_AUTHORITY}/{tenant}/oauth2/v2.0/token"
        resp = requests.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=timeout_seconds,
        )
        resp.raise_for_status()
        payload = resp.json()

        access_token = payload.get("access_token")
        if not access_token:
            raise RuntimeError(
                "Microsoft Graph token response did not include an access_token."
            )

        expires_in = int(payload.get("expires_in", 3600))
        _GRAPH_TOKEN_CACHE[client_id] = (time.time() + expires_in, access_token)
        return access_token


def _encode_sharing_url(sharepoint_url: str) -> str:
    """Encode a browser sharing URL into a Graph ``shares/`` resource id.

    Per the Graph "shares" API: base64-encode the URL, trim trailing ``=``
    padding, make it URL-safe, and prefix with ``u!``.
    """

    raw = base64.urlsafe_b64encode(sharepoint_url.strip().encode("utf-8")).decode("ascii")
    return "u!" + raw.rstrip("=")


def extract_sharepoint_text(
    sharepoint_url: Optional[str] = None,
    *,
    site_id: Optional[str] = None,
    drive_id: Optional[str] = None,
    item_id: Optional[str] = None,
    timeout_seconds: int = 30,
) -> str:
    """Fetch a SharePoint / OneDrive-for-Business file and extract its text.

    Provide either a shareable ``sharepoint_url`` (the link you get from the
    "Copy link" / address bar in SharePoint) or an explicit ``item_id`` plus
    one of ``drive_id`` / ``site_id``. The file is downloaded through Microsoft
    Graph with an app-only token and then run through :func:`extract_text`, so
    every format that direct uploads support (PDF, DOCX, TXT, image OCR) works
    here too.

    Raises:
        ValueError: if no locator is given, the credentials are missing, the
            file type is unsupported, the file is too large, or it yields no
            extractable text.
        RuntimeError: for Graph resolution / download failures.
    """

    if not sharepoint_url and not (item_id and (drive_id or site_id)):
        raise ValueError(
            "Provide a sharepoint_url, or item_id plus drive_id/site_id."
        )

    token = _get_graph_token(timeout_seconds=timeout_seconds)
    headers = {"Authorization": f"Bearer {token}"}

    if sharepoint_url:
        share_id = _encode_sharing_url(sharepoint_url)
        metadata_url = f"{config.GRAPH_BASE_URL}/shares/{share_id}/driveItem"
        content_url = f"{config.GRAPH_BASE_URL}/shares/{share_id}/driveItem/content"
    elif drive_id:
        metadata_url = f"{config.GRAPH_BASE_URL}/drives/{drive_id}/items/{item_id}"
        content_url = f"{metadata_url}/content"
    else:
        metadata_url = f"{config.GRAPH_BASE_URL}/sites/{site_id}/drive/items/{item_id}"
        content_url = f"{metadata_url}/content"

    logger.info("Resolving SharePoint item via Graph: %s", metadata_url)
    try:
        meta_resp = requests.get(metadata_url, headers=headers, timeout=timeout_seconds)
        meta_resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to resolve SharePoint item: {exc}") from exc

    metadata = meta_resp.json()
    file_name = str(metadata.get("name") or "sharepoint_document")
    declared_size = int(metadata.get("size", 0) or 0)
    if declared_size and declared_size > config.SHAREPOINT_MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"SharePoint file '{file_name}' is {declared_size} bytes, exceeding the "
            f"{config.SHAREPOINT_MAX_DOWNLOAD_BYTES}-byte limit."
        )

    suffix = Path(file_name).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported SharePoint file type: {suffix or '(none)'}")

    try:
        content_resp = requests.get(
            content_url, headers=headers, timeout=timeout_seconds, allow_redirects=True
        )
        content_resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to download SharePoint file content: {exc}") from exc

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(content_resp.content)
        tmp.close()
        text = extract_text(tmp.name)
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)

    if not text.strip():
        raise ValueError(
            f"SharePoint file '{file_name}' produced no extractable text."
        )
    logger.info("Extracted %d chars from SharePoint file '%s'.", len(text), file_name)
    return text