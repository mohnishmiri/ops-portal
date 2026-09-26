"""
Integration tests for CAT-B3 — CSV upload → validate → publish routes.

Verifies:
- POST /admin/catalog/preview compiles without persisting
- POST /admin/catalog/publish compiles and persists on success
- Capability gate (CATALOG_MANAGE) is enforced before the file is read
- CSRF is enforced before the file is read
- Compile failures return 400 with diagnostics, not a 500
- Version conflicts return 409 with both hashes

The real ``get_actor_context()`` dependency has no ``role_codes`` today
(CAT-SEC1b has not landed yet — see module docstring in
``catalog_admin_publish.py``), so the "success" tests below override the
dependency with a capability-bearing actor, and the "missing capability"
test either overrides with an empty-capability actor or relies on the real
dependency's current (always-empty) behavior — both are exercised here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from migration_intake.application.dto import ActorContext
from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.models import Actor, Base
from migration_intake.persistence.unit_of_work import uow_context
from migration_intake.web.routes.catalog_admin_publish import get_actor_context
from migration_intake.web.security import generate_csrf_token

CSV_HEADER = (
    "Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,"
    "Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination"
)
ROW_CTL_001 = (
    "CTL-001,CTL,What is the correlation ID?,IDENTIFIER,,REQUIRED,,Workbook,,"
    "Application Owner,ALL,ANSWER"
)
ROW_DB_001 = (
    "DB-001,DB,Does the application use a database?,BOOLEAN,YES|NO|UNKNOWN,"
    "REQUIRED,,Workbook|iTAP,,Application Owner,Topology,ANSWER"
)


def make_csv(*rows: str) -> bytes:
    return "\n".join((CSV_HEADER, *rows)).encode("utf-8")


VALID_CSV = make_csv(ROW_CTL_001)
VALID_CSV_DIFFERENT_CONTENT = make_csv(ROW_CTL_001, ROW_DB_001)
INVALID_CSV_DUPLICATE_ID = make_csv(ROW_CTL_001, ROW_CTL_001)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated, temp-file SQLite settings — never the real local.db."""
    db_path = tmp_path / "test.db"
    evidence_path = tmp_path / "evidence"
    evidence_path.mkdir()
    return Settings(
        database_url=f"sqlite:///{db_path}",
        app_env="test",
        actor_id=str(uuid.uuid4()),
        actor_display_name="Test Actor",
        evidence_root=evidence_path,
        csrf_secret="test-csrf-secret-for-catalog-admin-publish",
    )


@pytest.fixture
def app(settings: Settings):
    """Create the FastAPI app with tables created against the temp DB."""
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)

    now = datetime.now(tz=timezone.utc)
    with Session(application.state.engine) as session:
        session.add(
            Actor(id=settings.actor_id, display_name="Test Actor", created_at=now)
        )
        session.commit()

    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def csrf_token(settings: Settings) -> str:
    return generate_csrf_token(settings.csrf_secret)


@pytest.fixture
def capable_actor(settings: Settings) -> ActorContext:
    """An actor whose role_codes carries CATALOG_MANAGE."""
    return ActorContext(
        actor_id=str(settings.actor_id),
        role_codes=frozenset({"CATALOG_MANAGE"}),
    )


@pytest.fixture
def override_capable_actor(app, capable_actor: ActorContext):
    """Override get_actor_context to simulate a capability-bearing actor."""
    app.dependency_overrides[get_actor_context] = lambda: capable_actor
    yield
    app.dependency_overrides.pop(get_actor_context, None)


@pytest.fixture
def override_incapable_actor(app, settings: Settings):
    """Override get_actor_context to simulate an actor with no capabilities."""
    actor = ActorContext(actor_id=str(settings.actor_id), role_codes=frozenset())
    app.dependency_overrides[get_actor_context] = lambda: actor
    yield
    app.dependency_overrides.pop(get_actor_context, None)


def _release_count(app) -> int:
    with uow_context(app.state.session_factory) as uow:
        return len(uow.catalogs.list_releases())


def _files(content: bytes, filename: str = "catalog.csv"):
    return {"file": (filename, content, "text/csv")}


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestPublishSuccess:
    def test_valid_csv_publishes_and_is_retrievable(
        self, app, client: TestClient, csrf_token: str, override_capable_actor
    ) -> None:
        response = client.post(
            "/admin/catalog/publish",
            data={"_csrf_token": csrf_token, "semantic_version": "1.0.0"},
            files=_files(VALID_CSV),
        )

        assert response.status_code in (200, 201)
        body = response.json()
        assert body["semantic_version"] == "1.0.0"
        assert body["pub_state"] == "PUBLISHED"

        with uow_context(app.state.session_factory) as uow:
            persisted = uow.catalogs.get_release(body["id"])
        assert persisted is not None
        assert persisted["semantic_version"] == "1.0.0"

    def test_preview_does_not_persist(
        self, app, client: TestClient, csrf_token: str, override_capable_actor
    ) -> None:
        before = _release_count(app)

        response = client.post(
            "/admin/catalog/preview",
            data={"_csrf_token": csrf_token, "semantic_version": "1.0.0"},
            files=_files(VALID_CSV),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["is_success"] is True
        assert _release_count(app) == before


# ---------------------------------------------------------------------------
# CSRF gate
# ---------------------------------------------------------------------------


class TestCsrfGate:
    def test_missing_csrf_token_rejected_before_compile(
        self, app, client: TestClient, override_capable_actor, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        from migration_intake.catalog.compiler import CatalogCompiler

        monkeypatch.setattr(
            CatalogCompiler,
            "compile",
            lambda self, *a, **kw: calls.append("called"),
        )

        response = client.post(
            "/admin/catalog/publish",
            data={"_csrf_token": "not-a-real-token", "semantic_version": "1.0.0"},
            files=_files(VALID_CSV),
        )

        assert response.status_code == 403
        assert calls == []
        assert _release_count(app) == 0


# ---------------------------------------------------------------------------
# Capability gate
# ---------------------------------------------------------------------------


class TestCapabilityGate:
    def test_incapable_actor_rejected_before_compile(
        self,
        app,
        client: TestClient,
        csrf_token: str,
        override_incapable_actor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        from migration_intake.catalog.compiler import CatalogCompiler

        monkeypatch.setattr(
            CatalogCompiler,
            "compile",
            lambda self, *a, **kw: calls.append("called"),
        )

        response = client.post(
            "/admin/catalog/publish",
            data={"_csrf_token": csrf_token, "semantic_version": "1.0.0"},
            files=_files(VALID_CSV),
        )

        assert response.status_code == 403
        assert calls == []
        assert _release_count(app) == 0

    def test_real_dependency_now_has_capability(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """
        Regression guard for the CAT-SEC1b gap fix: the real
        get_actor_context() (no override) now grants
        CONFIGURED_ACTOR_CAPABILITIES, so an otherwise-valid request
        succeeds without needing a dependency override.
        """
        response = client.post(
            "/admin/catalog/publish",
            data={"_csrf_token": csrf_token, "semantic_version": "1.0.0"},
            files=_files(VALID_CSV),
        )

        assert response.status_code == 201
        assert _release_count(app) == 1


# ---------------------------------------------------------------------------
# Compile failure
# ---------------------------------------------------------------------------


class TestCompileFailure:
    def test_invalid_csv_returns_400_with_diagnostics(
        self, app, client: TestClient, csrf_token: str, override_capable_actor
    ) -> None:
        response = client.post(
            "/admin/catalog/publish",
            data={"_csrf_token": csrf_token, "semantic_version": "1.0.0"},
            files=_files(INVALID_CSV_DUPLICATE_ID),
        )

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "diagnostics" in detail
        assert len(detail["diagnostics"]) > 0
        assert _release_count(app) == 0


# ---------------------------------------------------------------------------
# Version conflict
# ---------------------------------------------------------------------------


class TestVersionConflict:
    def test_conflicting_version_returns_409_with_both_hashes(
        self, app, client: TestClient, csrf_token: str, override_capable_actor
    ) -> None:
        first = client.post(
            "/admin/catalog/publish",
            data={"_csrf_token": csrf_token, "semantic_version": "1.0.0"},
            files=_files(VALID_CSV),
        )
        assert first.status_code in (200, 201)

        with uow_context(app.state.session_factory) as uow:
            existing = uow.catalogs.get_release_by_version("1.0.0")
        existing_hash = existing["source_sha256"]

        import hashlib

        new_hash = hashlib.sha256(
            VALID_CSV_DIFFERENT_CONTENT.decode("utf-8-sig").encode("utf-8")
        ).hexdigest()

        second = client.post(
            "/admin/catalog/publish",
            data={"_csrf_token": csrf_token, "semantic_version": "1.0.0"},
            files=_files(VALID_CSV_DIFFERENT_CONTENT, filename="catalog-v2.csv"),
        )

        assert second.status_code == 409
        detail = second.json()["detail"]
        assert existing_hash in detail
        assert new_hash in detail
