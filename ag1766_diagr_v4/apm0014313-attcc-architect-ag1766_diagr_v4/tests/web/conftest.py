"""
Pytest configuration for tests/web — overrides the root test_client fixture.

The root conftest provides a minimal test_client that creates the app without
any database migrations or catalog data.  Now that the readiness endpoint
performs full checks (DB connectivity, schema version, evidence storage, and
published catalog), the readiness probe returns 503 in that minimal environment.

This local conftest provides a properly configured test_client so that every
existing test in test_health_bootstrap.py continues to pass:

  - Alembic migrations are applied to head revision (schema check passes).
  - One PUBLISHED CatalogRelease is inserted (catalog check passes).
  - Evidence root directory is created and writable (storage check passes).

Only the test_client fixture is overridden; local_env_settings is untouched.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPT_LOCATION = "src/migration_intake/persistence/migrations"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_migrations(db_path: Path) -> None:
    """Run Alembic upgrade to head on the given SQLite file."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _insert_published_catalog(db_path: Path) -> None:
    """Insert a single PUBLISHED CatalogRelease into a migrated database."""
    import migration_intake.persistence.models  # noqa: F401 — registers ORM tables

    from sqlalchemy.orm import Session

    from migration_intake.persistence.database import create_engine_from_url
    from migration_intake.persistence.models import CatalogRelease

    engine = create_engine_from_url(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    try:
        with Session(engine) as session:
            release = CatalogRelease(
                id=str(uuid.uuid4()),
                semantic_version="1.0.0",
                source_filename="seed_catalog.yaml",
                source_sha256="b" * 64,
                compiler_version="1.0.0",
                pub_state="PUBLISHED",
                published_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            session.add(release)
            session.commit()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Overridden fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Provide a FastAPI TestClient backed by a fully healthy environment.

    This overrides the root conftest fixture for all tests under tests/web/.
    The root fixture uses local_env_settings (no DATABASE_URL, no migrations)
    which is insufficient for the full readiness probe introduced in O02.

    Setup:
      1. Create a SQLite database file in tmp_path.
      2. Run Alembic migrations to head revision.
      3. Insert a PUBLISHED CatalogRelease.
      4. Create and configure the evidence root directory.
      5. Set all required environment variables via monkeypatch.
      6. Instantiate the FastAPI application and yield TestClient.
    """
    from fastapi.testclient import TestClient

    db_path = tmp_path / "web_test.db"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)

    _run_migrations(db_path)
    _insert_published_catalog(db_path)

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
    monkeypatch.setenv("ACTOR_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test Actor")
    monkeypatch.setenv("CSRF_SECRET", "test-csrf-secret-minimum-32-characters-long")

    from migration_intake.main import create_app

    app = create_app()

    with TestClient(app) as client:
        yield client

    app.state.engine.dispose()
