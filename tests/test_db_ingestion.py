"""Tests for `app.db_ingestion` (SQL row-serialization ingestion).

These exercise the SQLite path end to end (with a real temp database) plus the
read-only statement guards, which are database-agnostic.
"""

import sqlite3

import pytest

from app import db_ingestion
from app.db_ingestion import (
    _build_effective_query,
    _validate_identifier,
    _validate_select,
    extract_database_text,
    serialize_rows,
)


@pytest.fixture
def sample_db(tmp_path):
    path = tmp_path / "sample.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE policies (id INTEGER PRIMARY KEY, title TEXT, body TEXT);
        INSERT INTO policies (title, body) VALUES
            ('Leave Policy', 'Employees accrue 20 days per year.'),
            ('Travel Policy', 'Economy class for flights under 6 hours.');
        """
    )
    conn.commit()
    conn.close()
    return f"sqlite:///{path.as_posix()}"


def test_serialize_rows_labels_each_row():
    out = serialize_rows(["a", "b"], [(1, "x"), (2, "y")], label="widgets")

    assert "[widgets 1] a: 1; b: x" in out
    assert "[widgets 2] a: 2; b: y" in out


def test_serialize_rows_truncates_long_cells():
    out = serialize_rows(["c"], [("x" * 50,)], max_cell_chars=10)

    assert "xxxxxxxxxx…" in out


def test_validate_identifier_allows_schema_qualified():
    assert _validate_identifier("public.users") == "public.users"


def test_validate_identifier_rejects_injection():
    with pytest.raises(ValueError, match="Invalid table name"):
        _validate_identifier("users; DROP TABLE x")


def test_validate_select_rejects_non_select():
    with pytest.raises(ValueError, match="Only SELECT"):
        _validate_select("DELETE FROM policies")


def test_validate_select_rejects_multiple_statements():
    with pytest.raises(ValueError, match="Multiple SQL statements"):
        _validate_select("SELECT 1; DROP TABLE policies")


def test_validate_select_rejects_embedded_write_keyword():
    with pytest.raises(ValueError, match="disallowed keyword"):
        _validate_select("SELECT * FROM t WHERE note = 'do not delete'")


def test_build_effective_query_wraps_and_limits():
    assert (
        _build_effective_query("SELECT * FROM t", None, 10)
        == "SELECT * FROM (SELECT * FROM t) AS _rag_sub LIMIT 10"
    )
    assert _build_effective_query(None, "t", 5) == "SELECT * FROM t LIMIT 5"


def test_build_effective_query_requires_exactly_one_source():
    with pytest.raises(ValueError, match="exactly one"):
        _build_effective_query("SELECT 1", "t", 5)
    with pytest.raises(ValueError, match="exactly one"):
        _build_effective_query(None, None, 5)


def test_extract_database_text_from_table(sample_db):
    out = extract_database_text(connection_string=sample_db, table="policies")

    assert "Leave Policy" in out
    assert "Travel Policy" in out
    assert out.count("[policies ") == 2


def test_extract_database_text_from_query(sample_db):
    out = extract_database_text(
        connection_string=sample_db,
        query="SELECT title FROM policies WHERE title LIKE 'Leave%'",
    )

    assert "Leave Policy" in out
    assert "Travel Policy" not in out


def test_extract_database_text_row_cap(sample_db):
    out = extract_database_text(
        connection_string=sample_db, table="policies", max_rows=1
    )

    assert out.count("[policies ") == 1


def test_extract_database_text_rejects_unknown_scheme():
    with pytest.raises(ValueError, match="Unsupported database scheme"):
        extract_database_text(connection_string="mysql://localhost/x", table="t")


def test_extract_database_text_requires_dsn(monkeypatch):
    monkeypatch.setattr(db_ingestion.config, "DB_INGESTION_DSN", None)

    with pytest.raises(ValueError, match="No database connection string"):
        extract_database_text(table="t")


def test_extract_database_text_empty_result(sample_db):
    with pytest.raises(ValueError, match="no rows"):
        extract_database_text(
            connection_string=sample_db,
            query="SELECT * FROM policies WHERE 1 = 0",
        )


def test_extract_database_text_falls_back_to_env_dsn(sample_db, monkeypatch):
    monkeypatch.setattr(db_ingestion.config, "DB_INGESTION_DSN", sample_db)

    out = extract_database_text(table="policies")

    assert "Leave Policy" in out
