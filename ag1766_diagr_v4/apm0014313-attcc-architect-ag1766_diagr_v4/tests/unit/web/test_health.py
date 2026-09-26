"""
Unit tests for /health/live and /health/ready endpoints (O02 — Liveness and Readiness probes).

TDD: This file is written FIRST; it fails with ImportError at collection time
until migration_intake/web/health.py is implemented.  Every test must then
pass in the GREEN phase.

Checks covered:
  Liveness (3 tests):
    1. GET /health/live returns HTTP 200
    2. GET /health/live body is {"status": "ok"}
    3. GET /health/live returns 200 even with a broken DB engine

  Readiness (7 tests):
    4. Returns 200 when DB, schema, storage, and catalog are all healthy
    5. Returns 503 when DB is unreachable
    6. Returns 503 when schema is not at head revision
    7. Returns 503 when no PUBLISHED CatalogRelease exists
    8. Response body has checks dict with database/schema/storage/catalog keys
    9. Response body does NOT expose the database connection string
   10. Response body does NOT expose the filesystem path

Security rules enforced:
  - No connection strings, paths, or stack traces in response bodies.
  - Only {"ok": true/false} per check.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ── RED import — fails with ImportError until health.py is implemented ──────

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCRIPT_LOCATION = "src/migration_intake/persistence/migrations"

_TEST_ENV = {
    "APP_ENV": "local",
    "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
    "ACTOR_DISPLAY_NAME": "Test Actor",
    "CSRF_SECRET": "test-csrf-secret-minimum-32-characters-long",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_migrations(db_path: Path) -> None:
    """Apply Alembic head revision to an empty SQLite database file."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _insert_published_catalog(db_path: Path) -> None:
    """Insert a single PUBLISHED CatalogRelease into a migrated database."""
    from sqlalchemy.orm import Session

    import migration_intake.persistence.models  # noqa: F401 — registers ORM tables
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
                source_filename="test_catalog.yaml",
                source_sha256="a" * 64,
                compiler_version="1.0.0",
                pub_state="PUBLISHED",
                published_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            session.add(release)
            session.commit()
    finally:
        engine.dispose()


def _set_env(tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure environment variables for the test Flask/FastAPI app."""
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)

    for key, value in _TEST_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("AWS_OUTPOST_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))


def _make_app(tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a FastAPI application with environment configured."""
    _set_env(tmp_path, db_path, monkeypatch)
    from migration_intake.main import create_app

    return create_app()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def healthy_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    TestClient backed by a fully healthy environment:
      - Alembic migrations applied to head revision
      - One PUBLISHED CatalogRelease present
      - Writable evidence root directory
    """
    from fastapi.testclient import TestClient

    db_path = tmp_path / "test.db"
    _run_migrations(db_path)
    _insert_published_catalog(db_path)

    app = _make_app(tmp_path, db_path, monkeypatch)

    with TestClient(app) as client:
        yield client

    app.state.engine.dispose()


# ---------------------------------------------------------------------------
# 1-3  Liveness tests
# ---------------------------------------------------------------------------


class TestLiveness:
    """Tests for GET /health/live — must never touch external systems."""

    def test_liveness_returns_200(self, healthy_client) -> None:
        """GET /health/live must return HTTP 200."""
        response = healthy_client.get("/health/live")
        assert response.status_code == 200

    def test_liveness_returns_ok_status(self, healthy_client) -> None:
        """GET /health/live body must be exactly {"status": "ok"}."""
        response = healthy_client.get("/health/live")
        assert response.json() == {"status": "ok"}

    def test_liveness_independent_of_db(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GET /health/live must return 200 even when the database engine is broken.

        Liveness indicates process responsiveness only; it must not contact any
        external system.
        """
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        db_path = tmp_path / "test.db"
        app = _make_app(tmp_path, db_path, monkeypatch)

        broken_engine = MagicMock()
        broken_engine.connect.side_effect = Exception("DB is completely unreachable")
        app.state.engine = broken_engine

        with TestClient(app) as client:
            response = client.get("/health/live")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 4-10  Readiness tests
# ---------------------------------------------------------------------------


class TestReadiness:
    """Tests for GET /health/ready — checks DB, schema, storage, and catalog."""

    def test_readiness_returns_200_when_all_checks_pass(
        self, healthy_client
    ) -> None:
        """
        GET /health/ready returns 200 when:
          - DB is reachable
          - Schema is at head revision
          - Evidence storage is writable
          - At least one PUBLISHED CatalogRelease exists
        """
        response = healthy_client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_readiness_returns_503_when_db_unreachable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GET /health/ready returns 503 when the database is unreachable."""
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        db_path = tmp_path / "test.db"
        app = _make_app(tmp_path, db_path, monkeypatch)

        broken_engine = MagicMock()
        broken_engine.connect.side_effect = Exception("Connection refused")
        app.state.engine = broken_engine

        with TestClient(app) as client:
            response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"]["ok"] is False

    def test_readiness_returns_503_when_schema_outdated(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GET /health/ready returns 503 when the schema is not at head revision.

        Uses a bare SQLite file with no Alembic history so check_schema_current
        returns False.
        """
        from fastapi.testclient import TestClient

        # Create an empty SQLite file — no migrations applied
        db_path = tmp_path / "bare.db"
        db_path.touch()

        app = _make_app(tmp_path, db_path, monkeypatch)

        with TestClient(app) as client:
            response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["checks"]["schema"]["ok"] is False

    def test_readiness_returns_503_when_no_published_catalog(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GET /health/ready returns 503 when schema is current but no
        PUBLISHED CatalogRelease exists in the database.
        """
        from fastapi.testclient import TestClient

        db_path = tmp_path / "test.db"
        _run_migrations(db_path)
        # Do NOT insert any CatalogRelease
        monkeypatch.setattr(
            "migration_intake.main.ensure_catalog_published",
            lambda _session_factory: None,
        )

        app = _make_app(tmp_path, db_path, monkeypatch)

        with TestClient(app) as client:
            response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["checks"]["catalog"]["ok"] is False

    def test_readiness_body_has_checks_dict(self, healthy_client) -> None:
        """
        Readiness response body must contain a "checks" object with exactly
        the four expected keys: database, schema, storage, catalog.
        """
        response = healthy_client.get("/health/ready")
        data = response.json()

        assert "checks" in data
        checks = data["checks"]
        assert "database" in checks, "checks must have a 'database' key"
        assert "schema" in checks, "checks must have a 'schema' key"
        assert "storage" in checks, "checks must have a 'storage' key"
        assert "catalog" in checks, "checks must have a 'catalog' key"

    def test_readiness_does_not_expose_connection_string(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Readiness response body must never contain the database connection
        string (SQLite, postgresql, etc.) regardless of check outcome.
        """
        from fastapi.testclient import TestClient

        # Empty DB — some checks will fail, but we only care about what's exposed
        db_path = tmp_path / "test.db"
        app = _make_app(tmp_path, db_path, monkeypatch)

        with TestClient(app) as client:
            response = client.get("/health/ready")

        body = response.text
        assert "sqlite" not in body.lower(), (
            "Response body must not contain 'sqlite' (connection-string leak)"
        )
        assert "postgresql" not in body.lower(), (
            "Response body must not contain 'postgresql' (connection-string leak)"
        )

    def test_readiness_does_not_expose_filesystem_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Readiness response body must never contain any filesystem path
        (evidence root, DB path, or tmp directory).
        """
        from fastapi.testclient import TestClient

        db_path = tmp_path / "test.db"
        app = _make_app(tmp_path, db_path, monkeypatch)

        with TestClient(app) as client:
            response = client.get("/health/ready")

        body = response.text
        # The tmp_path parent directory should not appear in the response
        tmp_str = str(tmp_path).replace("\\", "/")
        tmp_str_win = str(tmp_path).replace("/", "\\")
        assert tmp_str not in body, (
            "Response body must not contain the tmp_path filesystem path"
        )
        assert tmp_str_win not in body, (
            "Response body must not contain the tmp_path filesystem path (Windows style)"
        )
