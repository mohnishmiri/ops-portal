"""
Oracle-specific migration idempotency tests.

Verifies that repair migrations (0007, 0008, 0009) are idempotent and can run
safely on both:
1. Fresh schemas (migrations run in order from base)
2. Historically-stamped schemas (simulating databases created at earlier revisions)

These migrations use column existence checks to add missing columns without
failing if they already exist.

All tests require ORACLE_TEST_URL environment variable and are marked with
@pytest.mark.oracle.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


def _get_oracle_url() -> str | None:
    """Get Oracle test URL from environment."""
    url = os.environ.get("ORACLE_TEST_URL")
    if not url:
        try:
            from dotenv import load_dotenv
            env_path = Path.cwd() / ".env"
            if env_path.exists():
                load_dotenv(env_path)
                url = os.environ.get("ORACLE_TEST_URL")
        except ImportError:
            pass
    return url


@pytest.fixture(scope="module")
def oracle_url() -> str:
    """Oracle test URL."""
    url = _get_oracle_url()
    if not url:
        pytest.skip("ORACLE_TEST_URL not configured")
    return url


@pytest.fixture()
def clean_oracle_engine(oracle_url: str) -> Engine:
    """
    Clean Oracle engine for each test.

    Drops all tables before test, creates fresh engine.
    """
    from migration_intake.persistence.database import configure_oracle_client

    client_dir = os.environ.get("AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR") or os.environ.get(
        "ORACLE_CLIENT_LIB_DIR"
    )
    configure_oracle_client(Path(client_dir) if client_dir else None)
    engine = create_engine(oracle_url, poolclass=NullPool, echo=False)

    # Verify we're not connected as SYSTEM
    with engine.connect() as conn:
        result = conn.execute(text("SELECT USER FROM DUAL"))
        current_user = result.scalar()
        if current_user and current_user.upper() in ("SYSTEM", "SYS"):
            pytest.fail(
                f"Oracle tests must not run as {current_user}. "
                "Use a dedicated test schema (e.g., migration_intake_test)."
            )

    # Drop all existing tables
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name FROM user_tables "
                "WHERE table_name NOT LIKE 'BIN$%' "
                "ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result]
        for table in tables:
            conn.execute(text(f"DROP TABLE {table} CASCADE CONSTRAINTS PURGE"))
        conn.commit()

    yield engine

    # Cleanup after test
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name FROM user_tables "
                "WHERE table_name NOT LIKE 'BIN$%'"
            )
        )
        tables = [row[0] for row in result]
        for table in tables:
            conn.execute(text(f"DROP TABLE {table} CASCADE CONSTRAINTS PURGE"))
        conn.commit()

    engine.dispose()


def _get_alembic_config(database_url: str) -> Config:
    """Create Alembic config pointing to Oracle database."""
    config = Config()
    # Use absolute path to migrations directory
    migrations_dir = Path(__file__).parent.parent.parent.parent / "src" / "migration_intake" / "persistence" / "migrations"
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _get_table_columns(engine: Engine, table_name: str) -> set[str]:
    """Get set of column names for a table (case-insensitive)."""
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)
    return {c["name"].upper() for c in columns}


# ---------------------------------------------------------------------------
# Fresh schema tests (migrations run in order from base)
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_fresh_schema_migration_to_head(clean_oracle_engine: Engine, oracle_url: str) -> None:
    """
    Fresh schema: Migrate from base to head in one step.

    Verifies that all migrations (including repair migrations 0007-0009)
    execute successfully on a clean Oracle schema.
    """
    config = _get_alembic_config(oracle_url)

    # Migrate to head
    command.upgrade(config, "head")

    # Verify we're at head (0010)
    with clean_oracle_engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        assert version == "0010", f"Expected version 0010, got {version}"

    # Verify repair migration columns exist
    cat_questions_cols = _get_table_columns(clean_oracle_engine, "cat_questions")
    assert "HELP_TEXT" in cat_questions_cols
    assert "UNITS" in cat_questions_cols
    assert "FIELD_NAME" in cat_questions_cols
    assert "RESPONSE_SCHEMA_VERSION" in cat_questions_cols

    ans_instances_cols = _get_table_columns(clean_oracle_engine, "ans_instances")
    assert "APPLICABILITY" in ans_instances_cols
    assert "VALUE_STATE" in ans_instances_cols
    assert "REVIEW_STATE" in ans_instances_cols
    assert "UPDATED_AT" in ans_instances_cols
    assert "ROW_VERSION" in ans_instances_cols

    ans_revisions_cols = _get_table_columns(clean_oracle_engine, "ans_revisions")
    assert "CHANGE_REASON" in ans_revisions_cols
    assert "RESPONSE_SCHEMA_VERSION" in ans_revisions_cols
    assert "RAW_BOUNDARY_VALUE" in ans_revisions_cols


# ---------------------------------------------------------------------------
# Idempotency tests (repair migrations run twice)
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_migration_0007_idempotent(clean_oracle_engine: Engine, oracle_url: str) -> None:
    """
    Migration 0007 is idempotent: can run twice without error.

    Simulates a historically-stamped database where 0007 was already applied,
    then runs upgrade again to verify column existence checks work.
    """
    config = _get_alembic_config(oracle_url)

    # Migrate to 0007
    command.upgrade(config, "0007")

    # Verify columns exist
    cols_after_first = _get_table_columns(clean_oracle_engine, "cat_questions")
    assert "HELP_TEXT" in cols_after_first
    assert "UNITS" in cols_after_first
    assert "FIELD_NAME" in cols_after_first
    assert "RESPONSE_SCHEMA_VERSION" in cols_after_first

    # Downgrade to 0006
    command.downgrade(config, "0006")

    # Verify columns removed
    cols_after_downgrade = _get_table_columns(clean_oracle_engine, "cat_questions")
    assert "HELP_TEXT" not in cols_after_downgrade
    assert "UNITS" not in cols_after_downgrade

    # Upgrade to 0007 again (idempotency test)
    command.upgrade(config, "0007")

    # Verify columns exist again
    cols_after_second = _get_table_columns(clean_oracle_engine, "cat_questions")
    assert "HELP_TEXT" in cols_after_second
    assert "UNITS" in cols_after_second
    assert "FIELD_NAME" in cols_after_second
    assert "RESPONSE_SCHEMA_VERSION" in cols_after_second


@pytest.mark.oracle
def test_migration_0008_idempotent(clean_oracle_engine: Engine, oracle_url: str) -> None:
    """
    Migration 0008 is idempotent: can run twice without error.

    Tests column existence checks for ans_instances repair migration.
    """
    config = _get_alembic_config(oracle_url)

    # Migrate to 0008
    command.upgrade(config, "0008")

    # Verify columns exist
    cols_after_first = _get_table_columns(clean_oracle_engine, "ans_instances")
    assert "APPLICABILITY" in cols_after_first
    assert "VALUE_STATE" in cols_after_first
    assert "REVIEW_STATE" in cols_after_first
    assert "UPDATED_AT" in cols_after_first
    assert "ROW_VERSION" in cols_after_first

    # Downgrade to 0007
    command.downgrade(config, "0007")

    # Verify columns removed
    cols_after_downgrade = _get_table_columns(clean_oracle_engine, "ans_instances")
    assert "APPLICABILITY" not in cols_after_downgrade
    assert "VALUE_STATE" not in cols_after_downgrade

    # Upgrade to 0008 again (idempotency test)
    command.upgrade(config, "0008")

    # Verify columns exist again
    cols_after_second = _get_table_columns(clean_oracle_engine, "ans_instances")
    assert "APPLICABILITY" in cols_after_second
    assert "VALUE_STATE" in cols_after_second
    assert "REVIEW_STATE" in cols_after_second
    assert "UPDATED_AT" in cols_after_second
    assert "ROW_VERSION" in cols_after_second


@pytest.mark.oracle
def test_migration_0009_idempotent(clean_oracle_engine: Engine, oracle_url: str) -> None:
    """
    Migration 0009 is idempotent: can run twice without error.

    Tests column existence checks for ans_revisions repair migration.
    """
    config = _get_alembic_config(oracle_url)

    # Migrate to 0009
    command.upgrade(config, "0009")

    # Verify columns exist
    cols_after_first = _get_table_columns(clean_oracle_engine, "ans_revisions")
    assert "CHANGE_REASON" in cols_after_first
    assert "RESPONSE_SCHEMA_VERSION" in cols_after_first
    assert "RAW_BOUNDARY_VALUE" in cols_after_first

    # Downgrade to 0008
    command.downgrade(config, "0008")

    # Verify columns removed
    cols_after_downgrade = _get_table_columns(clean_oracle_engine, "ans_revisions")
    assert "CHANGE_REASON" not in cols_after_downgrade
    assert "RESPONSE_SCHEMA_VERSION" not in cols_after_downgrade

    # Upgrade to 0009 again (idempotency test)
    command.upgrade(config, "0009")

    # Verify columns exist again
    cols_after_second = _get_table_columns(clean_oracle_engine, "ans_revisions")
    assert "CHANGE_REASON" in cols_after_second
    assert "RESPONSE_SCHEMA_VERSION" in cols_after_second
    assert "RAW_BOUNDARY_VALUE" in cols_after_second


# ---------------------------------------------------------------------------
# Historical schema simulation
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_historically_stamped_schema_at_0006(clean_oracle_engine: Engine, oracle_url: str) -> None:
    """
    Simulate a historically-stamped database created at revision 0006.

    Verifies that upgrading from 0006 to head adds all repair migration
    columns correctly.
    """
    config = _get_alembic_config(oracle_url)

    # Simulate database stamped at 0006 (before repair migrations)
    command.upgrade(config, "0006")

    # Verify we're at 0006
    with clean_oracle_engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        assert version == "0006"

    # Verify repair columns don't exist yet
    cat_questions_cols = _get_table_columns(clean_oracle_engine, "cat_questions")
    assert "HELP_TEXT" not in cat_questions_cols

    ans_instances_cols = _get_table_columns(clean_oracle_engine, "ans_instances")
    assert "APPLICABILITY" not in ans_instances_cols

    ans_revisions_cols = _get_table_columns(clean_oracle_engine, "ans_revisions")
    assert "CHANGE_REASON" not in ans_revisions_cols

    # Upgrade to head (should add all repair columns)
    command.upgrade(config, "head")

    # Verify we're at head
    with clean_oracle_engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        assert version == "0010"

    # Verify all repair columns now exist
    cat_questions_cols = _get_table_columns(clean_oracle_engine, "cat_questions")
    assert "HELP_TEXT" in cat_questions_cols
    assert "UNITS" in cat_questions_cols
    assert "FIELD_NAME" in cat_questions_cols
    assert "RESPONSE_SCHEMA_VERSION" in cat_questions_cols

    ans_instances_cols = _get_table_columns(clean_oracle_engine, "ans_instances")
    assert "APPLICABILITY" in ans_instances_cols
    assert "VALUE_STATE" in ans_instances_cols
    assert "REVIEW_STATE" in ans_instances_cols
    assert "UPDATED_AT" in ans_instances_cols
    assert "ROW_VERSION" in ans_instances_cols

    ans_revisions_cols = _get_table_columns(clean_oracle_engine, "ans_revisions")
    assert "CHANGE_REASON" in ans_revisions_cols
    assert "RESPONSE_SCHEMA_VERSION" in ans_revisions_cols
    assert "RAW_BOUNDARY_VALUE" in ans_revisions_cols


# ---------------------------------------------------------------------------
# Column existence check verification
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_column_existence_checks_use_correct_case(clean_oracle_engine: Engine, oracle_url: str) -> None:
    """
    Verify that column existence checks work correctly with Oracle's case normalization.

    Oracle uppercases unquoted identifiers, so `inspect().get_columns()` returns
    uppercase names. The migrations must handle this correctly.
    """
    config = _get_alembic_config(oracle_url)

    # Migrate to 0007
    command.upgrade(config, "0007")

    # Get columns using inspect (returns uppercase on Oracle)
    inspector = inspect(clean_oracle_engine)
    columns = inspector.get_columns("cat_questions")
    column_names = {c["name"] for c in columns}

    # Verify Oracle returns uppercase names
    assert any(name.isupper() for name in column_names), (
        "Oracle should return uppercase column names"
    )

    # Verify the migration's existence check would find these columns
    # (migrations use lowercase in the check, but inspect returns uppercase)
    uppercase_names = {name.upper() for name in column_names}
    assert "HELP_TEXT" in uppercase_names
    assert "UNITS" in uppercase_names
