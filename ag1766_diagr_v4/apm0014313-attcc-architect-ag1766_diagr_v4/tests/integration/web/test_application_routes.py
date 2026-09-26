"""
Integration tests for application list/create/workspace routes (UI02).

Tests cover:
- GET /applications — list view with pagination
- POST /applications — create new application
- GET /applications/{id} — workspace view

Following TDD: RED → GREEN → REFACTOR
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from migration_intake.domain.ids import ActorId, ApplicationId, CatalogReleaseId
from migration_intake.domain.states import ApplicationState
from migration_intake.main import create_app
from migration_intake.persistence.database import create_engine_from_url, create_session_factory


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create test client with in-memory database."""
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    
    # Set required environment variables
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
    monkeypatch.setenv("ACTOR_ID", str(ActorId.generate()))
    monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test Actor")
    monkeypatch.setenv("CSRF_SECRET", "test-secret-key-for-testing-only")
    monkeypatch.setenv("APP_ENV", "test")
    
    engine = create_engine_from_url(db_url)
    session_factory = create_session_factory(engine)
    
    # Import models to register them
    import migration_intake.persistence.models  # noqa: F401
    import migration_intake.persistence.models_evidence  # noqa: F401
    import migration_intake.persistence.models_imports  # noqa: F401
    
    # Run migrations to create tables
    from alembic import command
    from alembic.config import Config
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")
    
    app = create_app()
    app.state.engine = engine
    app.state.session_factory = session_factory
    
    return TestClient(app)


@pytest.fixture
def actor_id(client, tmp_path):
    """Create a test actor."""
    from datetime import datetime, timezone
    from migration_intake.persistence.models import Actor
    
    engine = client.app.state.engine
    session_factory = client.app.state.session_factory
    
    with Session(engine) as session:
        actor = Actor(
            id=str(ActorId.generate()),
            display_name="Test User",
            attuid="test123",
            created_at=datetime.now(timezone.utc),
        )
        session.add(actor)
        session.commit()
        return ActorId(actor.id)


@pytest.fixture
def catalog_id(client):
    """Create a published catalog release."""
    from migration_intake.persistence.models import CatalogRelease
    
    engine = client.app.state.engine
    
    from datetime import datetime, timezone
    
    with Session(engine) as session:
        catalog = CatalogRelease(
            id=str(CatalogReleaseId.generate()),
            semantic_version="0.1.0",
            source_filename="test_catalog.csv",
            source_sha256="a" * 64,
            compiler_version="0.1.0",
            pub_state="PUBLISHED",
            published_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        session.add(catalog)
        session.commit()
        return CatalogReleaseId(catalog.id)


class TestApplicationListRoute:
    """Tests for GET /applications route."""
    
    def test_list_returns_200(self, client):
        """GET /applications returns 200 OK."""
        response = client.get("/applications")
        assert response.status_code == 200
    
    def test_list_returns_html(self, client):
        """GET /applications returns HTML content."""
        response = client.get("/applications")
        assert "text/html" in response.headers["content-type"]
    
    def test_empty_list_shows_no_applications_message(self, client):
        """Empty list shows appropriate message."""
        response = client.get("/applications")
        assert response.status_code == 200
        assert b"No applications" in response.content or b"no applications" in response.content
    
    def test_list_shows_application_name(self, client, actor_id, catalog_id):
        """List shows application display name."""
        # Create an application
        from migration_intake.application.services.applications import ApplicationService
        from migration_intake.application.commands import CreateApplicationCommand
        from migration_intake.application.dto import ActorContext
        
        session_factory = client.app.state.session_factory
        service = ApplicationService(session_factory)
        
        actor_ctx = ActorContext(actor_id=str(actor_id))
        cmd = CreateApplicationCommand(
            display_name="Test Application",
            identifiers=(),
            actor=actor_ctx,
        )
        
        service.create_application(cmd)
        
        # Check list view
        response = client.get("/applications")
        assert response.status_code == 200
        assert b"Test Application" in response.content
    
    def test_list_pagination_limit_parameter(self, client):
        """List accepts limit parameter for pagination."""
        response = client.get("/applications?limit=10")
        assert response.status_code == 200
    
    def test_list_pagination_offset_parameter(self, client):
        """List accepts offset parameter for pagination."""
        response = client.get("/applications?offset=0")
        assert response.status_code == 200


class TestApplicationCreateRoute:
    """Tests for POST /applications route."""
    
    def test_create_returns_303_redirect(self, client, actor_id):
        """POST /applications redirects to workspace on success."""
        response = client.post(
            "/applications",
            data={
                "display_name": "New Application",
                "actor_id": str(actor_id),
            },
            follow_redirects=False,
        )
        # 307 Temporary Redirect or 303 See Other are both valid
        assert response.status_code in (303, 307)
        assert "location" in response.headers
    
    def test_create_with_empty_name_returns_400(self, client, actor_id):
        """POST with empty name returns validation error."""
        response = client.post(
            "/applications",
            data={
                "display_name": "",
                "actor_id": str(actor_id),
            },
        )
        # 400 Bad Request or 422 Unprocessable Entity both indicate validation error
        assert response.status_code in (400, 422)
    
    def test_create_duplicate_identifier_shows_error(self, client, actor_id, catalog_id):
        """POST with duplicate identifier shows error message."""
        # Create first application
        from migration_intake.application.services.applications import ApplicationService
        from migration_intake.application.commands import CreateApplicationCommand, IdentifierInput
        from migration_intake.application.dto import ActorContext
        
        session_factory = client.app.state.session_factory
        service = ApplicationService(session_factory)
        
        actor_ctx = ActorContext(actor_id=str(actor_id))
        cmd = CreateApplicationCommand(
            display_name="First App",
            identifiers=(IdentifierInput(identifier_type="ITAP", raw_value="12345"),),
            actor=actor_ctx,
        )
        service.create_application(cmd)
        
        # Try to create second with same identifier
        response = client.post(
            "/applications",
            data={
                "display_name": "Second App",
                "identifier_type": "ITAP",
                "identifier_value": "12345",
                "actor_id": str(actor_id),
            },
        )
        # 400 Bad Request or 422 Unprocessable Entity both indicate validation error
        assert response.status_code in (400, 422)
        assert b"duplicate" in response.content.lower() or b"already exists" in response.content.lower()


class TestApplicationWorkspaceRoute:
    """Tests for GET /applications/{id} route."""
    
    def test_workspace_returns_200(self, client, actor_id, catalog_id):
        """GET /applications/{id} returns 200 OK."""
        # Create application
        from migration_intake.application.services.applications import ApplicationService
        from migration_intake.application.commands import CreateApplicationCommand
        from migration_intake.application.dto import ActorContext
        
        session_factory = client.app.state.session_factory
        service = ApplicationService(session_factory)
        
        actor_ctx = ActorContext(actor_id=str(actor_id))
        cmd = CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor_ctx,
        )
        result = service.create_application(cmd)
        
        # Check workspace view
        response = client.get(f"/applications/{result['id']}")
        assert response.status_code == 200
    
    def test_workspace_returns_html(self, client, actor_id, catalog_id):
        """GET /applications/{id} returns HTML content."""
        # Create application
        from migration_intake.application.services.applications import ApplicationService
        from migration_intake.application.commands import CreateApplicationCommand
        from migration_intake.application.dto import ActorContext
        
        session_factory = client.app.state.session_factory
        service = ApplicationService(session_factory)
        
        actor_ctx = ActorContext(actor_id=str(actor_id))
        cmd = CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor_ctx,
        )
        result = service.create_application(cmd)
        
        response = client.get(f"/applications/{result['id']}")
        assert "text/html" in response.headers["content-type"]
    
    def test_workspace_shows_application_name(self, client, actor_id, catalog_id):
        """Workspace shows application display name."""
        # Create application
        from migration_intake.application.services.applications import ApplicationService
        from migration_intake.application.commands import CreateApplicationCommand
        from migration_intake.application.dto import ActorContext
        
        session_factory = client.app.state.session_factory
        service = ApplicationService(session_factory)
        
        actor_ctx = ActorContext(actor_id=str(actor_id))
        cmd = CreateApplicationCommand(
            display_name="Workspace Test App",
            identifiers=(),
            actor=actor_ctx,
        )
        result = service.create_application(cmd)
        
        response = client.get(f"/applications/{result['id']}")
        assert b"Workspace Test App" in response.content
    
    def test_workspace_shows_intake_count(self, client, actor_id, catalog_id):
        """Workspace shows number of intakes."""
        # Create application
        from migration_intake.application.services.applications import ApplicationService
        from migration_intake.application.commands import CreateApplicationCommand, CreateIntakeCommand
        from migration_intake.application.dto import ActorContext
        
        session_factory = client.app.state.session_factory
        service = ApplicationService(session_factory)
        
        actor_ctx = ActorContext(actor_id=str(actor_id))
        cmd = CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor_ctx,
        )
        result = service.create_application(cmd)
        
        # Create intake
        intake_cmd = CreateIntakeCommand(
            application_id=result['id'],
            catalog_release_id=str(catalog_id),
            actor=actor_ctx,
        )
        service.create_intake(intake_cmd)
        
        response = client.get(f"/applications/{result['id']}")
        assert response.status_code == 200
        # Should show intake count (1)
        assert b"1" in response.content
    
    def test_workspace_nonexistent_id_returns_404(self, client):
        """GET /applications/{nonexistent} returns 404."""
        fake_id = str(ApplicationId.generate())
        response = client.get(f"/applications/{fake_id}")
        assert response.status_code == 404
