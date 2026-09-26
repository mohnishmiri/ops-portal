"""
Pytest configuration and shared fixtures for Migration Intake tests.

This module provides:
- Test markers for categorizing tests
- Shared fixtures for configuration, database, and HTTP client
- Environment isolation for tests
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure tests run with isolated environment variables.

    Clears potentially conflicting environment variables and sets
    safe test defaults. This runs automatically for all tests.
    """
    # Clear any production-like settings that might leak from the environment
    env_vars_to_clear = [
        "APP_ENV",
        "DATABASE_URL",
        "EVIDENCE_ROOT",
        "ACTOR_ID",
        "ACTOR_DISPLAY_NAME",
        "CSRF_SECRET",
        "ORACLE_CLIENT_LIB_DIR",
        "STATIC_ASSETS_DIR",
        "LLM_ENABLED",
        "LLM_PROVIDER",
        "LLM_PROFILE",
        "LLM_OUTBOUND_ENABLED",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_AUTH_MODE",
        "LLM_API_TOKEN",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(f"AWS_OUTPOST_{var}", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AWS_OUTPOST_APP_ENV", "test")


@pytest.fixture
def local_env_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> dict[str, str]:
    """
    Provide valid local development environment settings.

    Returns a dictionary of environment variables suitable for
    local development/testing configuration.
    """
    evidence_root = tmp_path / "evidence"  # type: ignore[operator]
    evidence_root.mkdir(parents=True, exist_ok=True)

    settings = {
        "APP_ENV": "local",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
        "EVIDENCE_ROOT": str(evidence_root),
        "ACTOR_ID": "00000000-0000-0000-0000-000000000001",
        "ACTOR_DISPLAY_NAME": "Test Actor",
        "CSRF_SECRET": "test-csrf-secret-minimum-32-characters-long",
    }

    for key, value in settings.items():
        monkeypatch.setenv(key, value)

    return settings


@pytest.fixture
def test_client(local_env_settings: dict[str, str]) -> Generator[TestClient, None, None]:
    """
    Provide a FastAPI TestClient with isolated test configuration.

    This fixture ensures the application is created with test settings
    and properly cleaned up after the test.
    """
    import warnings

    # Suppress the httpx2 deprecation warning from starlette
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated",
            category=DeprecationWarning,
        )
        # Import here to avoid import-time side effects
        from fastapi.testclient import TestClient

    from migration_intake.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client
