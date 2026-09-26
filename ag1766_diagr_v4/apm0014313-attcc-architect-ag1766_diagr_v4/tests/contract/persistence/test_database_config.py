"""
Contract tests for SQLAlchemy engine configuration.

Verifies that SQLite pragmas are applied on every connection, that credentials
are redacted in diagnostic output, and that the session factory produces
usable sessions. These tests run against a real (temporary file) SQLite
database to catch connection-pool and pragma-event behaviour.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from migration_intake.persistence.database import (
    SQLITE_BUSY_TIMEOUT_MS,
    create_engine_from_url,
    create_session_factory,
    redact_url,
)


# ---------------------------------------------------------------------------
# Pragma enforcement
# ---------------------------------------------------------------------------


def test_sqlite_engine_enforces_foreign_keys(tmp_path: pytest.TempPathFactory) -> None:
    """SQLite connections must enforce foreign key constraints."""
    db_url = f"sqlite:///{tmp_path}/fk_test.db"
    engine = create_engine_from_url(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, f"Expected foreign_keys=1, got {result}"
    finally:
        engine.dispose()


def test_sqlite_engine_uses_wal_journal_mode(tmp_path: pytest.TempPathFactory) -> None:
    """SQLite must use WAL journal mode for concurrency."""
    db_url = f"sqlite:///{tmp_path}/wal_test.db"
    engine = create_engine_from_url(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert result.upper() == "WAL", f"Expected WAL, got {result}"
    finally:
        engine.dispose()


def test_sqlite_engine_busy_timeout_is_set(tmp_path: pytest.TempPathFactory) -> None:
    """SQLite busy timeout must be configured to the module constant."""
    db_url = f"sqlite:///{tmp_path}/timeout_test.db"
    engine = create_engine_from_url(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA busy_timeout")).scalar()
        assert result == SQLITE_BUSY_TIMEOUT_MS, (
            f"Expected busy_timeout={SQLITE_BUSY_TIMEOUT_MS}, got {result}"
        )
    finally:
        engine.dispose()


def test_sqlite_busy_timeout_constant_is_positive() -> None:
    """SQLITE_BUSY_TIMEOUT_MS must be a positive integer in milliseconds."""
    assert isinstance(SQLITE_BUSY_TIMEOUT_MS, int)
    assert SQLITE_BUSY_TIMEOUT_MS > 0


# ---------------------------------------------------------------------------
# In-memory vs file behaviour
# ---------------------------------------------------------------------------


def test_in_memory_sqlite_is_usable() -> None:
    """In-memory SQLite engine executes queries successfully."""
    engine = create_engine_from_url(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 42")).scalar()
        assert result == 42
    finally:
        engine.dispose()


def test_in_memory_sqlite_enforces_foreign_keys() -> None:
    """In-memory SQLite also enforces foreign keys."""
    engine = create_engine_from_url(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1
    finally:
        engine.dispose()


def test_file_database_persists_data_across_connections(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """File-based SQLite persists data that a second engine can read."""
    db_url = f"sqlite:///{tmp_path}/persist_test.db"

    engine1 = create_engine_from_url(db_url)
    try:
        with engine1.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS t (v INTEGER)"))
            conn.execute(text("INSERT INTO t VALUES (42)"))
            conn.commit()
    finally:
        engine1.dispose()

    engine2 = create_engine_from_url(db_url)
    try:
        with engine2.connect() as conn:
            result = conn.execute(text("SELECT v FROM t")).scalar()
        assert result == 42
    finally:
        engine2.dispose()


# ---------------------------------------------------------------------------
# Credential redaction
# ---------------------------------------------------------------------------


def test_redact_url_removes_password() -> None:
    """Credentials in a database URL are replaced with ***:***."""
    url = "postgresql+psycopg2://admin:s3cr3t@db.example.com:5432/mydb"
    redacted = redact_url(url)
    assert "s3cr3t" not in redacted
    assert "admin" not in redacted
    assert "***:***" in redacted
    assert "db.example.com:5432/mydb" in redacted


def test_redact_url_preserves_oracle_url_structure() -> None:
    """Oracle connection URLs are also redacted correctly."""
    url = "oracle+oracledb://appuser:apppass@localhost:1521/?service_name=FREEPDB1"
    redacted = redact_url(url)
    assert "apppass" not in redacted
    assert "appuser" not in redacted
    assert "***:***" in redacted
    assert "localhost:1521" in redacted


def test_redact_url_leaves_sqlite_url_unchanged() -> None:
    """SQLite URLs without userinfo are returned unchanged."""
    url = "sqlite:////data/migration.db"
    assert redact_url(url) == url


def test_redact_url_leaves_memory_url_unchanged() -> None:
    """In-memory SQLite URL is returned unchanged."""
    url = "sqlite:///:memory:"
    assert redact_url(url) == url


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------


def test_session_factory_produces_usable_session(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Session factory creates sessions that can execute queries."""
    db_url = f"sqlite:///{tmp_path}/session_test.db"
    engine = create_engine_from_url(db_url)
    try:
        factory = create_session_factory(engine)
        session = factory()
        try:
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1
        finally:
            session.close()
    finally:
        engine.dispose()


def test_session_factory_sessions_are_independent(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Two sessions from the same factory are independent objects."""
    db_url = f"sqlite:///{tmp_path}/independent_sessions.db"
    engine = create_engine_from_url(db_url)
    try:
        factory = create_session_factory(engine)
        s1 = factory()
        s2 = factory()
        try:
            assert s1 is not s2
        finally:
            s1.close()
            s2.close()
    finally:
        engine.dispose()
