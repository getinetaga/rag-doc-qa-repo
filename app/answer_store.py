"""Private answer retention, separate from caches, feedback and audit logs."""

from contextlib import contextmanager
import logging
from pathlib import Path
import sqlite3
import time
import uuid

from fastapi import HTTPException

from . import config

logger = logging.getLogger(__name__)
MAX_RECORDS = 1000


@contextmanager
def _database():
    connection = None
    try:
        path = Path(config.ANSWER_RETENTION_DB).expanduser()
        root = Path(__file__).resolve().parent.parent
        if (
            not config.ANSWER_RETENTION_DB or not path.is_absolute()
            or path.resolve().is_relative_to(root) or not path.parent.is_dir()
        ):
            raise HTTPException(503, "Private answer storage is not configured.")
        connection = sqlite3.connect(path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS answers (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL, collection_id TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL,
                stamp TEXT NOT NULL, status TEXT NOT NULL,
                question TEXT, answer TEXT
            )"""
        )
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            connection.execute(
                "DELETE FROM answers WHERE expires_at <= ? OR created_at + ? <= ?",
                (now, config.ANSWER_RETENTION_DAYS * 86400, now),
            )
            yield connection
    except (sqlite3.Error, OSError):
        logger.error("Private answer storage is unavailable.")
        raise HTTPException(503, "Private answer storage is unavailable.") from None
    finally:
        if connection is not None:
            connection.close()


def maintain(stamp: str | None) -> None:
    """Remove expired records and scrub invalidated payloads."""
    with _database() as connection:
        connection.execute(
            """UPDATE answers SET question = NULL, answer = NULL, status = 'redacted'
               WHERE status = 'available' AND (? IS NULL OR stamp != ?)""",
            (stamp, stamp),
        )


def save(owner_id: str, tenant_id: str, collection_id: str,
         question: str, answer: str, stamp: str) -> dict:
    if len(answer) > 100_000:
        raise HTTPException(422, "Answer exceeds the retained-content size limit.")
    now = time.time()
    answer_id = uuid.uuid4().hex
    expires_at = now + config.ANSWER_RETENTION_DAYS * 86400
    with _database() as connection:
        count = connection.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
        if count >= MAX_RECORDS:
            raise HTTPException(409, "Answer retention is full. Delete saved answers before retrying.")
        connection.execute(
            "INSERT INTO answers VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?, ?)",
            (answer_id, owner_id, tenant_id, collection_id, now, expires_at, stamp, question, answer),
        )
    return {"answer_id": answer_id, "answer_expires_at": expires_at}


def list_answers(owner_id: str, tenant_id: str, collection_id: str) -> list[dict]:
    with _database() as connection:
        rows = connection.execute(
            """SELECT id, created_at, expires_at, status FROM answers
               WHERE owner_id = ? AND tenant_id = ? AND collection_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (owner_id, tenant_id, collection_id, MAX_RECORDS),
        ).fetchall()
    return [dict(row) for row in rows]


def read(answer_id: str, owner_id: str) -> dict:
    with _database() as connection:
        row = connection.execute(
            "SELECT * FROM answers WHERE id = ? AND owner_id = ?", (answer_id, owner_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Saved answer not found.")
    return dict(row)


def delete(answer_id: str, owner_id: str) -> None:
    with _database() as connection:
        result = connection.execute(
            "DELETE FROM answers WHERE id = ? AND owner_id = ?", (answer_id, owner_id),
        )
        if result.rowcount != 1:
            raise HTTPException(404, "Saved answer not found.")
