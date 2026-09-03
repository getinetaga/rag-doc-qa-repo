"""Database (SQL) row-serialization ingestion.

Connects to a relational database, runs a single read-only ``SELECT``, and
renders the result set as plain text — one labeled block per row — so it can be
chunked, embedded, and indexed by the same pipeline that handles documents and
remote files.

Only PostgreSQL (via ``psycopg``, already a project dependency and imported
lazily) and SQLite (via the standard library) are supported. Writes are refused
at three layers:

1. the connection is opened read-only where the driver allows it,
2. the statement must be a lone ``SELECT`` / ``WITH`` with no data- or
   schema-modifying keywords, and
3. the row count is capped (``DB_INGESTION_MAX_ROWS``) both in SQL and while
   fetching.

The keyword filter is deliberately blunt and fails closed: a forbidden keyword
anywhere in the query — including inside a string literal such as
``WHERE note = 'do not delete'`` — is rejected. Rephrase such queries rather
than loosening the guard.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlparse

from . import config

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"postgresql", "postgres", "sqlite"}

# A plain table name, optionally schema-qualified (``schema.table``).
_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$"
)

# Whole-word data- or schema-modifying keywords that must not appear in a
# read-only query.
_FORBIDDEN_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|"
    r"MERGE|CALL|COPY|VACUUM|ATTACH|DETACH|PRAGMA|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)


def _validate_identifier(name: str) -> str:
    """Allow only a simple (optionally schema-qualified) table name."""

    if not _IDENTIFIER_RE.fullmatch(name or ""):
        raise ValueError(f"Invalid table name: {name!r}")
    return name


def _validate_select(query: str) -> str:
    """Return the query stripped of a trailing ``;`` after read-only checks."""

    cleaned = (query or "").strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty SQL query.")
    if ";" in cleaned:
        raise ValueError("Multiple SQL statements are not allowed.")
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", cleaned):
        raise ValueError("Only SELECT queries are allowed for database ingestion.")
    if _FORBIDDEN_SQL_RE.search(cleaned):
        raise ValueError("The SQL query contains a disallowed keyword.")
    if re.search(r"(?is)\bINTO\b", cleaned):
        raise ValueError("SELECT ... INTO is not allowed.")
    return cleaned


def _build_effective_query(
    query: Optional[str], table: Optional[str], max_rows: int
) -> str:
    """Compose the read-only, row-capped statement actually sent to the driver."""

    if bool(query) == bool(table):
        raise ValueError("Provide exactly one of 'query' or 'table'.")
    if table:
        return f"SELECT * FROM {_validate_identifier(table)} LIMIT {int(max_rows)}"
    inner = _validate_select(query or "")
    return f"SELECT * FROM ({inner}) AS _rag_sub LIMIT {int(max_rows)}"


def _render_cell(value: object, max_chars: int) -> str:
    """Collapse a single cell value to a single-line, length-capped string."""

    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def serialize_rows(
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    label: str = "row",
    max_cell_chars: int = 2000,
) -> str:
    """Render a result set as ``[label N] col: val; col: val`` blocks.

    The bracketed prefix doubles as a citation label: ``rag._extract_section_
    references`` picks it up so answers can point back to a specific row.
    """

    blocks = []
    for index, row in enumerate(rows, start=1):
        pairs = "; ".join(
            f"{col}: {_render_cell(val, max_cell_chars)}"
            for col, val in zip(columns, row)
        )
        blocks.append(f"[{label} {index}] {pairs}")
    return "\n\n".join(blocks)


def _fetch_sqlite(dsn: str, effective_query: str, max_rows: int):
    """Run the query against a SQLite file opened read-only."""

    parsed = urlparse(dsn)
    raw_path = (parsed.netloc or "") + (parsed.path or "")
    raw_path = raw_path.lstrip("/")
    if not raw_path or raw_path == ":memory:":
        raise ValueError(
            "SQLite ingestion needs a database file path, not an in-memory database."
        )

    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = db_path.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute(effective_query)
        columns = [d[0] for d in cur.description or []]
        fetched = cur.fetchmany(max_rows + 1)
        return columns, fetched[:max_rows], len(fetched) > max_rows
    finally:
        conn.close()


def _fetch_postgres(dsn: str, effective_query: str, max_rows: int):
    """Run the query against PostgreSQL in a read-only session."""

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - psycopg is a project dep
        raise ImportError(
            "PostgreSQL database ingestion requires the 'psycopg' package."
        ) from exc

    conn = psycopg.connect(dsn, autocommit=True)
    try:
        try:
            conn.read_only = True
        except Exception:  # pragma: no cover - best effort; SELECT filter still applies
            pass
        with conn.cursor() as cur:
            cur.execute(
                f"SET statement_timeout = {int(config.DB_INGESTION_STATEMENT_TIMEOUT_MS)}"
            )
            cur.execute(effective_query)
            columns = [d.name for d in cur.description or []]
            fetched = cur.fetchmany(max_rows + 1)
            return columns, fetched[:max_rows], len(fetched) > max_rows
    finally:
        conn.close()


def extract_database_text(
    *,
    connection_string: Optional[str] = None,
    query: Optional[str] = None,
    table: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> str:
    """Serialize the rows of a read-only ``SELECT`` into indexable text.

    Provide exactly one of ``table`` (fetched as ``SELECT * FROM <table>``) or
    ``query`` (an arbitrary read-only ``SELECT`` / ``WITH``). ``connection_string``
    falls back to ``config.DB_INGESTION_DSN``.

    Raises:
        ValueError: for a missing/blocked connection string, an unsupported
            scheme, a non-read-only or multi-statement query, a bad table name,
            or an empty result set.
        FileNotFoundError: if a SQLite path does not exist.
        ImportError: if a PostgreSQL DSN is used without ``psycopg`` installed.
    """

    dsn = (connection_string or config.DB_INGESTION_DSN or "").strip()
    if not dsn:
        raise ValueError(
            "No database connection string provided and DB_INGESTION_DSN is not set."
        )

    scheme = (urlparse(dsn).scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Unsupported database scheme: {scheme or '(none)'}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SCHEMES))}."
        )

    row_cap = int(max_rows or config.DB_INGESTION_MAX_ROWS)
    if row_cap <= 0:
        raise ValueError("max_rows must be greater than zero.")

    effective_query = _build_effective_query(query, table, row_cap)
    label = _validate_identifier(table) if table else "row"

    if scheme == "sqlite":
        columns, rows, truncated = _fetch_sqlite(dsn, effective_query, row_cap)
    else:
        columns, rows, truncated = _fetch_postgres(dsn, effective_query, row_cap)

    if not rows:
        raise ValueError("The database query returned no rows.")

    text = serialize_rows(
        columns,
        rows,
        label=label,
        max_cell_chars=config.DB_INGESTION_MAX_CELL_CHARS,
    )
    logger.info(
        "Serialized %d row(s) x %d column(s) from database ingestion%s.",
        len(rows),
        len(columns),
        " (row cap reached)" if truncated else "",
    )
    return text
