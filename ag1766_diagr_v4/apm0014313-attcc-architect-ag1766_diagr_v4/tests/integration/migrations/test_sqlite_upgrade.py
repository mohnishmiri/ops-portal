"""
Integration tests for P03: Alembic baseline migration (SQLite).

These tests verify that:
- An empty SQLite database upgrades cleanly to head.
- All 12 domain tables are created after upgrade.
- Running upgrade twice (already at head) is safe.
- Downgrade from head to base removes all domain tables.
- Creating an engine / session factory does NOT auto-migrate.
- A fresh empty database is detected as behind by check_schema_current().
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from migration_intake.persistence.database import (
    check_schema_current,
    create_engine_from_url,
    create_session_factory,
)

if TYPE_CHECKING:
    import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Absolute Alembic script location so isolated test cwd cannot load repository .env.
_SCRIPT_LOCATION = str(
    Path(__file__).resolve().parents[3]
    / "src"
    / "migration_intake"
    / "persistence"
    / "migrations"
)

#: All 12 domain tables that must exist after a full upgrade.
EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "actors",
        "applications",
        "app_identifiers",
        "cat_releases",
        "cat_sections",
        "cat_questions",
        "cat_options",
        "cat_src_rels",
        "intakes",
        "ans_instances",
        "ans_revisions",
        "audit_events",
    }
)

#: Expected head revision for the current codebase.
HEAD_REVISION = "0022"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(db_path: str) -> Config:
    """Return a minimal Alembic Config pointing at the test database."""
    cfg = Config()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_sqlite_upgrades_to_head(tmp_path: pytest.TempPathFactory) -> None:
    """An empty SQLite file upgrades cleanly to the current head revision."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    engine.dispose()

    assert len(rows) == 1, f"Expected exactly one revision row, got {rows}"
    assert rows[0][0] == HEAD_REVISION, (
        f"Expected revision '{HEAD_REVISION}', got '{rows[0][0]}'"
    )


def test_all_12_tables_exist_after_upgrade(tmp_path: pytest.TempPathFactory) -> None:
    """After upgrade, all 12 domain tables exist in the SQLite schema."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    engine.dispose()

    missing = EXPECTED_TABLES - tables
    assert not missing, f"Tables missing after upgrade: {sorted(missing)}"


def test_c7_capture_columns_exist_after_upgrade(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Head includes the intake epoch and immutable compatibility pins."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    command.upgrade(_alembic_cfg(db_file), "head")

    engine = create_engine(f"sqlite:///{db_file}")
    inspector = inspect(engine)
    intake_columns = {column["name"] for column in inspector.get_columns("intakes")}
    input_columns = {column["name"] for column in inspector.get_columns("topo_inputs")}
    input_foreign_keys = {
        foreign_key["name"] for foreign_key in inspector.get_foreign_keys("topo_inputs")
    }
    engine.dispose()

    assert "content_epoch" in intake_columns
    assert {
        "compatibility_id",
        "compatibility_key",
        "compatibility_result_hash",
    } <= input_columns
    assert "fk_tinp_cmp" in input_foreign_keys
    run_columns = {column["name"] for column in inspector.get_columns("gen_runs")}
    assert "rerun_reason" in run_columns


def test_upgrade_is_idempotent(tmp_path: pytest.TempPathFactory) -> None:
    """Running upgrade twice (already at head) is safe and produces no error."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # second call must not raise


def test_downgrade_removes_tables(tmp_path: pytest.TempPathFactory) -> None:
    """Downgrade from head to base removes all domain tables cleanly."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(f"sqlite:///{db_file}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    engine.dispose()

    remaining = EXPECTED_TABLES.intersection(tables)
    assert not remaining, (
        f"Domain tables still present after downgrade to base: {sorted(remaining)}"
    )


def test_application_does_not_auto_migrate(tmp_path: pytest.TempPathFactory) -> None:
    """Creating an engine and session factory does not run migrations automatically."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    engine = create_engine_from_url(f"sqlite:///{db_file}")
    # Creating a session factory must NOT create any tables
    _factory = create_session_factory(engine)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    engine.dispose()

    auto_created = EXPECTED_TABLES.intersection(tables)
    assert not auto_created, (
        f"Tables were auto-created (should require explicit migration): {sorted(auto_created)}"
    )


def test_schema_check_detects_empty_db(tmp_path: pytest.TempPathFactory) -> None:
    """A fresh empty database is detected as behind/incompatible by check_schema_current."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    engine = create_engine(f"sqlite:///{db_file}")
    result = check_schema_current(engine)
    engine.dispose()

    assert result is False, (
        "check_schema_current() should return False for a database "
        "with no alembic_version table."
    )


def test_schema_check_returns_true_after_upgrade(tmp_path: pytest.TempPathFactory) -> None:
    """check_schema_current() returns True after a successful upgrade to head."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    result = check_schema_current(engine)
    engine.dispose()

    assert result is True, (
        "check_schema_current() should return True when schema is at head revision."
    )
