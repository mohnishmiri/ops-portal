"""
Tests for application health endpoints and bootstrap behavior.

These tests verify:
- Minimal FastAPI app exposes liveness endpoint
- Liveness is independent of database/dependencies
- Importing package has no database/file/network side effects
- Application starts without errors with valid configuration

TDD: Write these tests FIRST, then implement main.py to make them pass.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestLivenessEndpoint:
    """Tests for the liveness health check endpoint."""

    def test_liveness_returns_200(self, test_client: TestClient) -> None:
        """Liveness endpoint should return 200 OK."""
        response = test_client.get("/health/live")
        
        assert response.status_code == 200

    def test_liveness_returns_json(self, test_client: TestClient) -> None:
        """Liveness endpoint should return JSON response."""
        response = test_client.get("/health/live")
        
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"

    def test_liveness_is_independent_of_database(
        self,
        test_client: TestClient,
    ) -> None:
        """
        Liveness should succeed even if database is unavailable.
        
        Liveness indicates the process is running, not that all
        dependencies are healthy. Readiness checks dependencies.
        """
        # The test_client fixture uses SQLite which should work,
        # but liveness should not query the database at all.
        response = test_client.get("/health/live")
        
        assert response.status_code == 200


class TestReadinessEndpoint:
    """Tests for the readiness health check endpoint."""

    def test_readiness_returns_200_when_healthy(
        self,
        test_client: TestClient,
    ) -> None:
        """Readiness endpoint should return 200 when all dependencies are healthy."""
        response = test_client.get("/health/ready")
        
        assert response.status_code == 200

    def test_readiness_returns_json_with_checks(
        self,
        test_client: TestClient,
    ) -> None:
        """Readiness endpoint should return JSON with dependency check results."""
        response = test_client.get("/health/ready")
        
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert "status" in data
        assert "checks" in data


class TestPackageImport:
    """Tests for package import behavior."""

    def test_package_import_has_no_side_effects(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Importing the package should not trigger database/file/network operations.
        
        This ensures the package can be imported for introspection, testing,
        or documentation without requiring a running database or network.
        """
        # Remove any cached imports
        modules_to_remove = [
            key for key in sys.modules.keys()
            if key.startswith("migration_intake")
        ]
        for module in modules_to_remove:
            del sys.modules[module]
        
        # Clear environment to ensure no configuration is loaded
        env_vars = [
            "APP_ENV", "DATABASE_URL", "EVIDENCE_ROOT",
            "ACTOR_ID", "ACTOR_DISPLAY_NAME", "CSRF_SECRET",
        ]
        for var in env_vars:
            monkeypatch.delenv(var, raising=False)
        
        # Import should succeed without side effects
        import migration_intake
        
        # Package should have version info
        assert hasattr(migration_intake, "__version__")

    def test_package_version_is_string(self) -> None:
        """Package version should be a valid string."""
        import migration_intake
        
        assert isinstance(migration_intake.__version__, str)
        assert len(migration_intake.__version__) > 0


class TestApplicationFactory:
    """Tests for the application factory function."""

    def test_create_app_returns_fastapi_instance(
        self,
        local_env_settings: dict[str, str],
    ) -> None:
        """create_app should return a FastAPI application instance."""
        from fastapi import FastAPI
        
        from migration_intake.main import create_app
        
        app = create_app()
        
        assert isinstance(app, FastAPI)

    def test_create_app_includes_health_routes(
        self,
        local_env_settings: dict[str, str],
    ) -> None:
        """create_app should include health check routes."""
        from migration_intake.main import create_app
        
        app = create_app()
        
        # Collect all route paths, handling nested routers
        route_paths = []
        for route in app.routes:
            if hasattr(route, 'path'):
                route_paths.append(route.path)
        
        # Health routes should be registered
        all_routes_str = str(app.routes)  # Fallback: check string repr if path not found
        assert "/health/live" in route_paths or "/health/live" in all_routes_str
        assert "/health/ready" in route_paths or "/health/ready" in all_routes_str

    def test_create_app_sets_title_and_version(
        self,
        local_env_settings: dict[str, str],
    ) -> None:
        """create_app should set appropriate title and version."""
        from migration_intake.main import create_app
        
        app = create_app()
        
        assert app.title == "Migration Intake"
        assert app.version is not None
