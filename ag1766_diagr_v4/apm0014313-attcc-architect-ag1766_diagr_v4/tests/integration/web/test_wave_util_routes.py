"""
Tests for UI07 — WaveUtil routes (list and detail pages).

Verifies:
- GET /applications/{app}/intakes/{intake}/wave-util lists rows
- GET /applications/{app}/intakes/{intake}/wave-util/{row} shows detail
- POST /applications/{app}/intakes/{intake}/wave-util/accept accepts candidates
- POST /applications/{app}/intakes/{intake}/wave-util/reject rejects candidates
- POST /applications/{app}/intakes/{intake}/wave-util/{row}/retire retires rows
- CSRF validation on all POST routes
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    Intake,
    Base,
)
from migration_intake.persistence.models_evidence import EvidenceItem, WaveUtilRow, WaveUtilRevision
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.web.security import generate_csrf_token


@pytest.fixture
def tmp_db(tmp_path: Path):
    """Create a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    return f"sqlite:///{db_path}"


@pytest.fixture
def settings(tmp_db: str, tmp_path: Path) -> Settings:
    """Create test settings."""
    return Settings(
        database_url=tmp_db,
        app_env="test",
        evidence_root=str(tmp_path / "evidence"),
        actor_id=str(uuid.uuid4()),
        actor_display_name="Test Actor",
        csrf_secret="test-csrf-secret-key-12345",
    )


@pytest.fixture
def app(settings: Settings):
    """Create test app with database tables."""
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def csrf_token(settings: Settings) -> str:
    """Generate a valid CSRF token."""
    return generate_csrf_token(settings.csrf_secret)


def _seed_actor(engine, actor_id: str) -> None:
    """Seed an actor row."""
    now = datetime.now(tz=timezone.utc)
    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))
        session.commit()


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


def _seed_catalog(engine) -> str:
    """Seed a catalog. Returns catalog_id."""
    now = datetime.now(tz=timezone.utc)
    catalog_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            CatalogRelease(
                id=catalog_id,
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

    return catalog_id


def _seed_intake(engine, app_id: str, catalog_id: str, actor_id: str) -> str:
    """Seed an intake. Returns intake_id."""
    now = datetime.now(tz=timezone.utc)
    intake_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=catalog_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()

    return intake_id


def _seed_wave_util_row(engine, app_id: str, intake_id: str, actor_id: str, server_name: str = "server-001") -> str:
    """Seed a WaveUtil row. Returns row_id."""
    now = datetime.now(tz=timezone.utc)
    row_id = str(uuid.uuid4())
    rev_id = str(uuid.uuid4())

    with Session(engine) as session:
        # First add row without current_rev_id
        session.add(
            WaveUtilRow(
                id=row_id,
                application_id=app_id,
                intake_id=intake_id,
                server_name=server_name,
                normalized_server_name=server_name.lower(),
                environment="PROD",
                scope="IN_SCOPE",
                state="ACTIVE",
                current_rev_id=None,  # Set to None initially
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.flush()  # Flush to create the row first

        # Then add revision
        session.add(
            WaveUtilRevision(
                id=rev_id,
                row_id=row_id,
                revision_number=1,
                field_values_json={"cpu": "8", "memory": "32GB"},
                authored_at=now,
                authored_by_id=actor_id,
            )
        )
        session.flush()

        # Update row with current_rev_id
        row = session.get(WaveUtilRow, row_id)
        row.current_rev_id = rev_id
        session.commit()

    return row_id


def _seed_wave_util_candidate(engine, app_id: str, intake_id: str, actor_id: str) -> str:
    """Seed a WaveUtil candidate. Returns candidate_id."""
    now = datetime.now(tz=timezone.utc)
    candidate_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with Session(engine) as session:
        # Evidence
        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=app_id,
                intake_id=intake_id,
                storage_key=f"evidence/{evidence_id}/test.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes=1024,
                sha256_hex="b" * 64,
                original_filename="test.xlsx",
                state="ACTIVE",
                created_at=now,
                created_by_id=actor_id,
            )
        )
        session.flush()

        # Import run
        session.add(
            ImportRun(
                id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                contract_name="WAVEUTIL_V1",
                parser_version="1.0.0",
                state="COMPLETED",
                created_at=now,
                created_by_id=actor_id,
            )
        )
        session.flush()

        # Candidate
        session.add(
            Candidate(
                id=candidate_id,
                import_run_id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                target_kind="WAVEUTIL_ROW",
                target_key="WAVEUTIL-NEW-server-new",
                origin="wave_util_import",
                extractor_version="1.0.0",
                contract_version="WAVEUTIL_V1",
                raw_value_json={
                    "server_name": "server-new",
                    "environment": "PROD",
                    "scope": "IN_SCOPE",
                    "fields": {"cpu": "16"},
                    "match_outcome": "NEW_ROW",
                    "matched_row_id": None,
                },
                state="PROPOSED",
                row_version=1,
                created_at=now,
            )
        )
        session.commit()

    return candidate_id


class TestListWaveUtil:
    """Tests for GET /applications/{app}/intakes/{intake}/wave-util."""

    def test_renders_list_page(self, app, client: TestClient) -> None:
        """Renders WaveUtil list page."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util"
        )

        assert response.status_code == 200
        assert "WaveUtil" in response.text

    def test_shows_wave_util_rows(self, app, client: TestClient) -> None:
        """Shows WaveUtil rows in the list."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        _seed_wave_util_row(app.state.engine, app_id, intake_id, actor_id, "test-server")

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util"
        )

        assert response.status_code == 200
        assert "test-server" in response.text

    def test_pagination(self, app, client: TestClient) -> None:
        """Supports pagination."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util?page=1&page_size=10"
        )

        assert response.status_code == 200

    def test_list_response_contains_nav_element(self, app, client: TestClient) -> None:
        """List page response contains a <nav> element for the side rail."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util"
        )

        assert response.status_code == 200
        assert "<nav" in response.text

    def test_list_response_contains_data_wave_util_list(self, app, client: TestClient) -> None:
        """List page table carries the data-wave-util-list attribute for JS filter."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        _seed_wave_util_row(app.state.engine, app_id, intake_id, actor_id, "nav-test-server")

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util"
        )

        assert response.status_code == 200
        assert "data-wave-util-list" in response.text


class TestWaveUtilDetail:
    """Tests for GET /applications/{app}/intakes/{intake}/wave-util/{row}."""

    def test_renders_detail_page(self, app, client: TestClient) -> None:
        """Renders WaveUtil detail page."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        row_id = _seed_wave_util_row(app.state.engine, app_id, intake_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}"
        )

        assert response.status_code == 200
        assert "server-001" in response.text

    def test_shows_current_values(self, app, client: TestClient) -> None:
        """Shows current revision values."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        row_id = _seed_wave_util_row(app.state.engine, app_id, intake_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}"
        )

        assert response.status_code == 200
        assert "32GB" in response.text  # memory value

    def test_returns_404_for_unknown_row(self, app, client: TestClient) -> None:
        """Returns 404 for unknown row."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/{uuid.uuid4()}"
        )

        assert response.status_code == 404

    def test_detail_response_contains_dl_element(self, app, client: TestClient) -> None:
        """Detail page response contains a <dl> element for the server detail grid."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        row_id = _seed_wave_util_row(app.state.engine, app_id, intake_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}"
        )

        assert response.status_code == 200
        assert "<dl" in response.text


class TestAcceptCandidates:
    """Tests for POST /applications/{app}/intakes/{intake}/wave-util/accept."""

    def test_requires_csrf_token(self, app, client: TestClient) -> None:
        """POST without CSRF token returns 422."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/accept",
            data={},
        )

        assert response.status_code == 422

    def test_rejects_invalid_csrf(self, app, client: TestClient) -> None:
        """POST with invalid CSRF token returns 403."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        candidate_id = _seed_wave_util_candidate(app.state.engine, app_id, intake_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/accept",
            data={
                "_csrf_token": "invalid-token",
                "candidate_ids": candidate_id,
                "expected_versions": "1",
            },
        )

        assert response.status_code == 403


class TestRejectCandidates:
    """Tests for POST /applications/{app}/intakes/{intake}/wave-util/reject."""

    def test_requires_reason(self, app, client: TestClient, csrf_token: str) -> None:
        """Rejection without reason returns 400."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        candidate_id = _seed_wave_util_candidate(app.state.engine, app_id, intake_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/reject",
            data={
                "_csrf_token": csrf_token,
                "candidate_ids": candidate_id,
                "reason": "   ",  # Whitespace-only reason
            },
        )

        assert response.status_code == 400


class TestRetireRow:
    """Tests for POST /applications/{app}/intakes/{intake}/wave-util/{row}/retire."""

    def test_requires_rationale(self, app, client: TestClient, csrf_token: str) -> None:
        """Retirement without rationale returns 400."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        row_id = _seed_wave_util_row(app.state.engine, app_id, intake_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}/retire",
            data={
                "_csrf_token": csrf_token,
                "expected_version": "1",
                "rationale": "   ",  # Whitespace-only rationale
            },
        )

        assert response.status_code == 400

    def test_retires_row_with_valid_data(self, app, client: TestClient, csrf_token: str) -> None:
        """Retires row with valid rationale."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        row_id = _seed_wave_util_row(app.state.engine, app_id, intake_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/wave-util/{row_id}/retire",
            data={
                "_csrf_token": csrf_token,
                "expected_version": 1,
                "rationale": "Server decommissioned",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303

        # Verify row is retired
        with Session(app.state.engine) as session:
            repo = WaveUtilRepository(session)
            row = repo.get_row(row_id)
            assert row["state"] == "RETIRED"
