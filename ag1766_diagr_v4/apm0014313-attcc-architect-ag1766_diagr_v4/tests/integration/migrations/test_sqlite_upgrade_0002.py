"""
Integration tests for P05: Alembic migration 0002 — evidence and wave_util tables (SQLite).

These tests verify that:
- Migration 0002 creates evidence_items, wave_util_rows, wave_util_revisions.
- Downgrade from 0002 to 0001 removes the three new tables.
- The UNIQUE constraint on (application_id, normalized_server_name) is enforced.
"""

from __future__ import annotations

import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCRIPT_LOCATION = "src/migration_intake/persistence/migrations"

#: Three tables added by migration 0002.
NEW_TABLES: frozenset[str] = frozenset(
    {
        "evidence_items",
        "wave_util_rows",
        "wave_util_revisions",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(db_path: str) -> Config:
    """Return a minimal Alembic Config pointing at the test database."""
    cfg = Config()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Test 1 — upgrade to 0002 creates all three new tables
# ---------------------------------------------------------------------------


def test_upgrade_0002_creates_tables(tmp_path: pytest.TempPathFactory) -> None:
    """Run migrations up to 0002; verify all three new tables exist."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "0002")

    engine = create_engine(f"sqlite:///{db_file}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    engine.dispose()

    missing = NEW_TABLES - tables
    assert not missing, f"Tables missing after upgrade to 0002: {sorted(missing)}"

    # Verify alembic_version is at 0002
    engine2 = create_engine(f"sqlite:///{db_file}")
    with engine2.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    engine2.dispose()
    assert len(rows) == 1
    assert rows[0][0] == "0002"


# ---------------------------------------------------------------------------
# Test 2 — downgrade from 0002 to 0001 removes the three new tables
# ---------------------------------------------------------------------------


def test_downgrade_0002_removes_tables(tmp_path: pytest.TempPathFactory) -> None:
    """Downgrade from 0002 to 0001; verify the three new tables are removed."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "0002")
    command.downgrade(cfg, "0001")

    engine = create_engine(f"sqlite:///{db_file}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    engine.dispose()

    still_present = NEW_TABLES.intersection(tables)
    assert not still_present, (
        f"New tables still present after downgrade to 0001: {sorted(still_present)}"
    )

    # Verify alembic_version is at 0001
    engine2 = create_engine(f"sqlite:///{db_file}")
    with engine2.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    engine2.dispose()
    assert len(rows) == 1
    assert rows[0][0] == "0001"


# ---------------------------------------------------------------------------
# Test 3 — UNIQUE constraint on (application_id, normalized_server_name)
# ---------------------------------------------------------------------------


def test_wave_util_unique_constraint(tmp_path: pytest.TempPathFactory) -> None:
    """After 0002, inserting duplicate (application_id, normalized_server_name) raises."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "0002")

    engine = create_engine(f"sqlite:///{db_file}")

    now_str = "2025-01-01T12:00:00+00:00"
    actor_id = _uid()
    app_id = _uid()
    row_id_1 = _uid()
    row_id_2 = _uid()

    # Insert prerequisites (no FK enforcement on plain create_engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO actors (id, display_name, created_at)"
                " VALUES (:id, :dn, :ca)"
            ),
            {"id": actor_id, "dn": "Test Actor", "ca": now_str},
        )
        conn.execute(
            text(
                "INSERT INTO applications"
                " (id, state, display_name, created_at, updated_at, row_version, created_by_id)"
                " VALUES (:id, 'ACTIVE', 'App', :ca, :ua, 1, :cbi)"
            ),
            {"id": app_id, "ca": now_str, "ua": now_str, "cbi": actor_id},
        )
        # First wave_util_rows row — succeeds
        conn.execute(
            text(
                "INSERT INTO wave_util_rows"
                " (id, application_id, intake_id, server_name, normalized_server_name,"
                "  environment, scope, state, current_rev_id,"
                "  created_at, updated_at, row_version, created_by_id)"
                " VALUES (:id, :app, NULL, 'Srv', 'srv', NULL, NULL,"
                "  'ACTIVE', NULL, :ca, :ua, 1, :cbi)"
            ),
            {
                "id": row_id_1,
                "app": app_id,
                "ca": now_str,
                "ua": now_str,
                "cbi": actor_id,
            },
        )

    # Second row with same (application_id, normalized_server_name) must raise
    with pytest.raises(Exception):  # IntegrityError from the UNIQUE constraint
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO wave_util_rows"
                    " (id, application_id, intake_id, server_name, normalized_server_name,"
                    "  environment, scope, state, current_rev_id,"
                    "  created_at, updated_at, row_version, created_by_id)"
                    " VALUES (:id, :app, NULL, 'Srv', 'srv', NULL, NULL,"
                    "  'ACTIVE', NULL, :ca, :ua, 1, :cbi)"
                ),
                {
                    "id": row_id_2,
                    "app": app_id,
                    "ca": now_str,
                    "ua": now_str,
                    "cbi": actor_id,
                },
            )

    engine.dispose()
