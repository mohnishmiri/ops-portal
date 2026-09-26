"""
Integration tests for P05b: Alembic migration 0003 — import_runs, import_sheet_results,
import_findings tables (SQLite).

These tests verify that:
- Migration 0003 creates import_runs, import_sheet_results, import_findings.
- Downgrade from 0003 to 0002 removes the three new tables.
- Finding severity values are storable (ERROR, WARNING, INFO).
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

#: Three tables added by migration 0003.
NEW_TABLES: frozenset[str] = frozenset(
    {
        "import_runs",
        "import_sheet_results",
        "import_findings",
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
# Test 1 — upgrade to 0003 creates all three new tables
# ---------------------------------------------------------------------------


def test_upgrade_0003_creates_tables(tmp_path: pytest.TempPathFactory) -> None:
    """Run migrations up to 0003; verify all three new tables exist."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "0003")

    engine = create_engine(f"sqlite:///{db_file}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    engine.dispose()

    missing = NEW_TABLES - tables
    assert not missing, f"Tables missing after upgrade to 0003: {sorted(missing)}"

    # Verify alembic_version is at 0003
    engine2 = create_engine(f"sqlite:///{db_file}")
    with engine2.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    engine2.dispose()
    assert len(rows) == 1
    assert rows[0][0] == "0003"


# ---------------------------------------------------------------------------
# Test 2 — downgrade from 0003 to 0002 removes the three new tables
# ---------------------------------------------------------------------------


def test_downgrade_0003_removes_tables(tmp_path: pytest.TempPathFactory) -> None:
    """Downgrade from 0003 to 0002; verify the three new tables are removed."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "0003")
    command.downgrade(cfg, "0002")

    engine = create_engine(f"sqlite:///{db_file}")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    engine.dispose()

    still_present = NEW_TABLES.intersection(tables)
    assert not still_present, (
        f"New tables still present after downgrade to 0002: {sorted(still_present)}"
    )

    # Verify alembic_version is at 0002
    engine2 = create_engine(f"sqlite:///{db_file}")
    with engine2.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    engine2.dispose()
    assert len(rows) == 1
    assert rows[0][0] == "0002"


# ---------------------------------------------------------------------------
# Test 3 — finding severity values are storable
# ---------------------------------------------------------------------------


def test_finding_severity_stored(tmp_path: pytest.TempPathFactory) -> None:
    """After 0003 upgrade, severity values ERROR/WARNING/INFO are all insertable."""
    db_file = str(tmp_path / "test.db")  # type: ignore[operator]
    cfg = _alembic_cfg(db_file)
    command.upgrade(cfg, "0003")

    engine = create_engine(f"sqlite:///{db_file}")

    now_str = "2025-06-01T10:00:00+00:00"
    actor_id = _uid()
    app_id = _uid()
    run_id = _uid()

    with engine.begin() as conn:
        # Insert prerequisites
        conn.execute(
            text("INSERT INTO actors (id, display_name, created_at) VALUES (:id, :dn, :ca)"),
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
        # Insert import_runs row
        conn.execute(
            text(
                "INSERT INTO import_runs"
                " (id, application_id, intake_id, evidence_item_id,"
                "  contract_name, parser_version, state,"
                "  total_candidates, total_findings, created_at, created_by_id)"
                " VALUES (:id, :app, NULL, NULL, 'TEST', '1.0.0', 'PENDING', 0, 0, :ca, :cbi)"
            ),
            {"id": run_id, "app": app_id, "ca": now_str, "cbi": actor_id},
        )

        # Insert findings with all severity levels
        for severity in ("ERROR", "WARNING", "INFO"):
            conn.execute(
                text(
                    "INSERT INTO import_findings"
                    " (id, run_id, sheet_name, finding_type, severity,"
                    "  source_locator, detail)"
                    " VALUES (:id, :rid, 'Sheet1', 'TEST_TYPE', :sev, NULL, NULL)"
                ),
                {"id": _uid(), "rid": run_id, "sev": severity},
            )

    # Read back and verify all three severities were stored
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT severity FROM import_findings WHERE run_id = :rid ORDER BY severity"),
            {"rid": run_id},
        ).fetchall()

    engine.dispose()

    severities = {r[0] for r in rows}
    assert severities == {"ERROR", "WARNING", "INFO"}, (
        f"Not all severity values stored; got: {severities}"
    )
