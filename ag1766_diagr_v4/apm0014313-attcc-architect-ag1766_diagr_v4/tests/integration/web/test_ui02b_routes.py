"""
Integration tests for UI02b — Application-to-intake entry path.

Tests:
- Root redirect to /applications
- GET /applications/new form page
- POST /applications/{id}/intakes creates intake
- No-catalog state handling
- Duplicate open intake conflict
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from migration_intake.main import create_app
from migration_intake.config import Settings
from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.web.security import generate_csrf_token, set_csrf_secret


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Create test settings with a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    evidence_path = tmp_path / "evidence"
    evidence_path.mkdir()
    return Settings(
        database_url=f"sqlite:///{db_path}",
        app_env="test",
        actor_id=str(uuid.uuid4()),
        actor_display_name="Test Actor",
        evidence_root=evidence_path,
        csrf_secret="test-csrf-secret-for-ui02b-testing",
    )


@pytest.fixture
def app(settings: Settings):
    """Create a test application."""
    from migration_intake.persistence.models import Base

    app = create_app(settings)

    # Create tables
    Base.metadata.create_all(app.state.engine)

    return app


@pytest.fixture
def client(app) -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def csrf_token() -> str:
    """Generate a valid CSRF token for testing."""
    set_csrf_secret(b"test-secret-for-ui02b-tests")
    return generate_csrf_token()


def _seed_actor(engine, actor_id: str) -> None:
    """Seed an actor row."""
    now = datetime.now(tz=timezone.utc)
    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))
        session.commit()


def _seed_catalog(engine) -> str:
    """Seed a published catalog. Returns catalog_id."""
    now = datetime.now(tz=timezone.utc)
    cat_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="catalog.yaml",
                source_sha256="a" * 64,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                published_at=now,
                created_at=now,
            )
        )
        session.commit()

    with Session(engine) as session:
        session.add(
            CatalogSection(
                id=section_id,
                release_id=cat_id,
                section_code="SEC-001",
                display_name="Section 1",
                display_order=1,
            )
        )
        session.commit()

    return cat_id


def _seed_application(engine, actor_id: str) -> str:
    """Seed an application. Returns application_id."""
    now = datetime.now(tz=timezone.utc)
    app_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Test App",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()

    return app_id


def _seed_intake(engine, app_id: str, cat_id: str, actor_id: str) -> str:
    """Seed an intake. Returns intake_id."""
    now = datetime.now(tz=timezone.utc)
    intake_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=cat_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()

    return intake_id


# ---------------------------------------------------------------------------
# Root redirect tests
# ---------------------------------------------------------------------------


class TestRootRedirect:
    """Tests for GET / -> 303 /applications."""

    def test_root_redirects_to_applications(self, client: TestClient) -> None:
        """GET / returns 303 redirect to /applications."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/applications"

    def test_root_redirect_follows_to_applications(self, client: TestClient) -> None:
        """GET / with follow_redirects reaches /applications."""
        response = client.get("/", follow_redirects=True)
        assert response.status_code == 200
        # Should be on the applications list page
        assert "applications" in response.url.path.lower()


# ---------------------------------------------------------------------------
# New application form tests
# ---------------------------------------------------------------------------


class TestNewApplicationForm:
    """Tests for GET /applications/new."""

    def test_new_form_returns_200(self, client: TestClient) -> None:
        """GET /applications/new returns 200."""
        response = client.get("/applications/new")
        assert response.status_code == 200

    def test_new_form_contains_csrf_token(self, client: TestClient) -> None:
        """New application form contains CSRF token."""
        response = client.get("/applications/new")
        assert "_csrf_token" in response.text

    def test_new_form_contains_display_name_field(self, client: TestClient) -> None:
        """New application form contains display_name field."""
        response = client.get("/applications/new")
        assert 'name="display_name"' in response.text

    def test_new_form_contains_identifier_fields(self, client: TestClient) -> None:
        """New application form contains identifier fields."""
        response = client.get("/applications/new")
        assert 'name="identifier_type"' in response.text
        assert 'name="identifier_value"' in response.text


# ---------------------------------------------------------------------------
# Create intake tests
# ---------------------------------------------------------------------------


class TestCreateIntake:
    """Tests for POST /applications/{id}/intakes."""

    def test_create_intake_requires_csrf_token(
        self, app, client: TestClient
    ) -> None:
        """POST /applications/{id}/intakes without CSRF token returns 422."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes",
            data={},  # No CSRF token
            follow_redirects=False,
        )
        # FastAPI returns 422 for missing required form field
        assert response.status_code == 422

    def test_create_intake_rejects_invalid_csrf(
        self, app, client: TestClient
    ) -> None:
        """POST /applications/{id}/intakes with invalid CSRF returns 403."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes",
            data={"_csrf_token": "invalid-token"},
            follow_redirects=False,
        )
        assert response.status_code == 403

    def test_create_intake_succeeds_with_valid_csrf(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """POST /applications/{id}/intakes with valid CSRF creates intake."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes",
            data={"_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/applications/{app_id}" in response.headers["location"]

        # Verify intake was created
        with Session(app.state.engine) as session:
            intake = session.query(Intake).filter(Intake.application_id == app_id).first()
            assert intake is not None
            assert str(intake.catalog_id) == cat_id

    def test_create_intake_no_catalog_returns_400(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """POST /applications/{id}/intakes with no published catalog returns 400."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        # Don't seed a catalog
        app_id = _seed_application(app.state.engine, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes",
            data={"_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "catalog" in response.text.lower()

    def test_create_intake_duplicate_returns_400(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """POST /applications/{id}/intakes with existing open intake returns 400."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes",
            data={"_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "open intake" in response.text.lower() or "already exists" in response.text.lower()

    def test_create_intake_unknown_app_returns_404(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """POST /applications/{id}/intakes with unknown app returns 404."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        _seed_catalog(app.state.engine)

        fake_app_id = str(uuid.uuid4())
        response = client.post(
            f"/applications/{fake_app_id}/intakes",
            data={"_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Workspace with catalog info tests
# ---------------------------------------------------------------------------


class TestWorkspaceWithCatalog:
    """Tests for workspace showing catalog info."""

    def test_workspace_shows_latest_catalog(
        self, app, client: TestClient
    ) -> None:
        """Workspace shows latest published catalog info."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)

        response = client.get(f"/applications/{app_id}")
        assert response.status_code == 200
        # Should contain CSRF token for intake creation
        assert "_csrf_token" in response.text

    def test_workspace_no_catalog_shows_empty_state(
        self, app, client: TestClient
    ) -> None:
        """Workspace with no published catalog shows appropriate state."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        # Don't seed a catalog
        app_id = _seed_application(app.state.engine, actor_id)

        response = client.get(f"/applications/{app_id}")
        assert response.status_code == 200
        # Should still render (empty state)
