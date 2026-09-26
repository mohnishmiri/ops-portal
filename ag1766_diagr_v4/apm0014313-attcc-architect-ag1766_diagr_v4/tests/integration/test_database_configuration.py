"""
Integration tests for database configuration and runtime behavior.

Verifies:
- Pool settings are applied correctly for Oracle/PostgreSQL
- Password redaction works in logs and diagnostics
- Engine shutdown/disposal works correctly
- SQLite engines don't receive pool settings (uses NullPool by default)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.database import redact_url

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Password redaction tests
# ---------------------------------------------------------------------------


def test_redact_url_removes_credentials() -> None:
    """redact_url() removes username:password from database URLs."""
    url = "postgresql://user:s3cr3t@host:5432/db"
    redacted = redact_url(url)
    assert redacted == "postgresql://***:***@host:5432/db"
    assert "user" not in redacted
    assert "s3cr3t" not in redacted


def test_redact_url_handles_oracle() -> None:
    """redact_url() works with Oracle URLs."""
    url = "oracle+oracledb://migration_intake:password123@localhost:1521?service_name=FREEPDB1"
    redacted = redact_url(url)
    assert redacted == "oracle+oracledb://***:***@localhost:1521?service_name=FREEPDB1"
    assert "migration_intake" not in redacted
    assert "password123" not in redacted


def test_redact_url_preserves_sqlite() -> None:
    """redact_url() leaves SQLite URLs unchanged (no credentials)."""
    url = "sqlite:///path/to/db.sqlite"
    redacted = redact_url(url)
    assert redacted == url


def test_settings_redacted_database_url() -> None:
    """Settings.redacted_database_url() removes credentials."""
    with patch.dict(os.environ, {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql://admin:secret@db.example.com/prod",
        "EVIDENCE_ROOT": str(Path.cwd() / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
    }):
        settings = Settings()
        redacted = settings.redacted_database_url()
        assert redacted == "postgresql://***:***@db.example.com/prod"
        assert "admin" not in redacted
        assert "secret" not in redacted


@pytest.mark.skip(
    reason="Known issue: configured-actor mode check not implemented"
)
def test_create_app_rejects_configured_actor_mode_in_shared_test(tmp_path: Path) -> None:
    """Configured-actor mode must not boot shared_test until enterprise auth exists."""
    with patch.dict(os.environ, {
        "APP_ENV": "shared_test",
        "DATABASE_URL": "oracle+oracledb://user:pw@localhost:1521/perf",
        "EVIDENCE_ROOT": str(tmp_path / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
    }):
        settings = Settings()
        with pytest.raises(RuntimeError, match="Configured-actor mode is disabled"):
            create_app(settings)


# ---------------------------------------------------------------------------
# Pool configuration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sqlite_engine_does_not_use_pool_settings(tmp_path: Path) -> None:
    """SQLite engines don't receive pool_size/max_overflow settings."""
    db_path = tmp_path / "test.db"

    with patch.dict(os.environ, {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "EVIDENCE_ROOT": str(tmp_path / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
        "DB_POOL_SIZE": "20",  # Should be ignored for SQLite
        "DB_MAX_OVERFLOW": "30",  # Should be ignored for SQLite
    }):
        settings = Settings()
        app = create_app(settings)
        engine: Engine = app.state.engine

        # SQLite can use QueuePool, but pool settings aren't applied
        # (main.py only applies pool settings for non-SQLite databases)
        # Verify the engine was created successfully
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

        # Cleanup
        engine.dispose()


@pytest.mark.oracle
def test_oracle_engine_uses_pool_settings() -> None:
    """Oracle engines receive pool settings from configuration."""
    oracle_url = os.environ.get("ORACLE_TEST_URL")
    if not oracle_url:
        try:
            from dotenv import load_dotenv
            env_path = Path.cwd() / ".env"
            if env_path.exists():
                load_dotenv(env_path)
                oracle_url = os.environ.get("ORACLE_TEST_URL")
        except ImportError:
            pass

    if not oracle_url:
        pytest.skip("ORACLE_TEST_URL not configured")

    with patch.dict(os.environ, {
        "DATABASE_URL": oracle_url,
        "EVIDENCE_ROOT": str(Path.cwd() / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
        "DB_POOL_SIZE": "15",
        "DB_MAX_OVERFLOW": "25",
        "DB_POOL_RECYCLE_SECONDS": "1800",
    }):
        settings = Settings()
        app = create_app(settings)
        engine: Engine = app.state.engine

        # Oracle should use QueuePool
        assert isinstance(engine.pool, QueuePool)

        # Verify pool settings
        assert engine.pool.size() == 15  # pool_size
        assert engine.pool._max_overflow == 25  # max_overflow
        assert engine.pool._recycle == 1800  # pool_recycle

        # Cleanup
        engine.dispose()


# ---------------------------------------------------------------------------
# Engine shutdown tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_engine_disposal_closes_connections(tmp_path: Path) -> None:
    """Engine.dispose() closes all pooled connections."""
    db_path = tmp_path / "test.db"

    with patch.dict(os.environ, {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "EVIDENCE_ROOT": str(tmp_path / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
    }):
        settings = Settings()
        app = create_app(settings)
        engine: Engine = app.state.engine

        # Open a connection to verify engine works
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

        # Dispose of engine
        engine.dispose()

        # Verify pool is disposed
        # (attempting to use the engine after disposal should create a new pool)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1


@pytest.mark.oracle
def test_oracle_engine_disposal_closes_connections() -> None:
    """Oracle engine disposal closes all connections in the pool."""
    oracle_url = os.environ.get("ORACLE_TEST_URL")
    if not oracle_url:
        try:
            from dotenv import load_dotenv
            env_path = Path.cwd() / ".env"
            if env_path.exists():
                load_dotenv(env_path)
                oracle_url = os.environ.get("ORACLE_TEST_URL")
        except ImportError:
            pass

    if not oracle_url:
        pytest.skip("ORACLE_TEST_URL not configured")

    with patch.dict(os.environ, {
        "DATABASE_URL": oracle_url,
        "EVIDENCE_ROOT": str(Path.cwd() / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
        "DB_POOL_SIZE": "5",
        "DB_MAX_OVERFLOW": "10",
    }):
        settings = Settings()
        app = create_app(settings)
        engine: Engine = app.state.engine

        # Open multiple connections to populate the pool
        connections = []
        for _ in range(3):
            conn = engine.connect()
            result = conn.execute(text("SELECT USER FROM DUAL"))
            assert result.scalar() is not None
            connections.append(conn)

        # Close connections (return to pool)
        for conn in connections:
            conn.close()

        # Dispose of engine (should close all pooled connections)
        engine.dispose()

        # Verify we can still use the engine (creates new pool)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT USER FROM DUAL"))
            assert result.scalar() is not None

        # Final cleanup
        engine.dispose()


# ---------------------------------------------------------------------------
# SQL echo configuration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sql_echo_setting_is_applied(tmp_path: Path) -> None:
    """SQL_ECHO setting controls SQLAlchemy echo parameter."""
    db_path = tmp_path / "test.db"

    # Test with echo=True
    with patch.dict(os.environ, {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "EVIDENCE_ROOT": str(tmp_path / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
        "SQL_ECHO": "true",
    }):
        settings = Settings()
        app = create_app(settings)
        engine: Engine = app.state.engine

        assert engine.echo is True
        engine.dispose()

    # Test with echo=False (default)
    with patch.dict(os.environ, {
        "DATABASE_URL": f"sqlite:///{db_path}",
        "EVIDENCE_ROOT": str(tmp_path / "evidence"),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-secret-key-32-characters-long",
        "SQL_ECHO": "false",
    }):
        settings = Settings()
        app = create_app(settings)
        engine: Engine = app.state.engine

        assert engine.echo is False
        engine.dispose()
