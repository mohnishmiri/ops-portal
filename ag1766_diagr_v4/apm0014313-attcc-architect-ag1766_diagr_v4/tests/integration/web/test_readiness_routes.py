"""
Integration tests for readiness and snapshot routes — UI08 / UX-4b.

Verifies:
- GET /intakes/{id}/readiness returns readiness status with nav
- POST /intakes/{id}/freeze requires CSRF token, creates snapshot
- GET /intakes/{id}/snapshot returns snapshot details with frozen banner
- GET /intakes/{id}/export returns canonical package
- JSON API endpoints work correctly
- app_id=None (orphaned intake) renders gracefully without nav rail
"""

from __future__ import annotations

import json
from io import BytesIO
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from openpyxl import load_workbook

from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    CatalogSection,
    CatalogQuestion,
    Intake,
    Base,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.web.security import generate_csrf_token


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Create test settings with SQLite database."""
    db_path = tmp_path / "test.db"
    return Settings(
        database_url=f"sqlite:///{db_path}",
        app_env="test",
        evidence_root=str(tmp_path / "evidence"),
        actor_id=str(uuid.uuid4()),
        actor_display_name="Test Actor",
        csrf_secret="test-csrf-secret-key-12345",
    )


@pytest.fixture
def test_app(test_settings):
    """Create test application."""
    app = create_app(test_settings)
    return app


@pytest.fixture
def client(test_app) -> TestClient:
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def session_factory(test_app):
    """Get session factory from app state."""
    return test_app.state.session_factory


@pytest.fixture
def seeded_db(test_app, session_factory, test_settings) -> dict:
    """Seed database with test data and create tables."""
    # Create tables
    Base.metadata.create_all(test_app.state.engine)

    now = datetime.now(tz=timezone.utc)

    with session_factory() as session:
        # Actor - use the actor_id from settings so freeze can use it
        actor_id = test_settings.actor_id
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))

        # Application
        app_id = str(uuid.uuid4())
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

        # Catalog
        catalog_id = str(uuid.uuid4())
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

        # Intake
        intake_id = str(uuid.uuid4())
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

        return {
            "actor_id": actor_id,
            "app_id": app_id,
            "catalog_id": catalog_id,
            "intake_id": intake_id,
        }


def _csrf(test_settings: Settings) -> str:
    """Generate a valid CSRF token for the test app's secret."""
    return generate_csrf_token(test_settings.csrf_secret)


class TestReadinessEndpoint:
    """Tests for GET /intakes/{id}/readiness."""

    def test_returns_readiness_html(self, client: TestClient, seeded_db: dict) -> None:
        """Returns HTML readiness page with design-system markup."""
        response = client.get(f"/intakes/{seeded_db['intake_id']}/readiness")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Title block renders
        assert "Readiness" in response.text

    def test_readiness_page_has_nav(self, client: TestClient, seeded_db: dict) -> None:
        """Nav rail is present in the readiness page."""
        response = client.get(f"/intakes/{seeded_db['intake_id']}/readiness")

        assert response.status_code == 200
        assert "<nav" in response.text

    def test_readiness_page_has_no_tailwind_classes(
        self, client: TestClient, seeded_db: dict
    ) -> None:
        """The readiness page contains no Tailwind utility class patterns."""
        response = client.get(f"/intakes/{seeded_db['intake_id']}/readiness")

        assert response.status_code == 200
        # Known Tailwind class patterns from the old template
        for bad_class in [
            "mx-auto", "px-4", "py-8", "text-2xl", "font-bold",
            "bg-white", "shadow", "rounded-lg", "bg-green-100",
            "text-green-800", "rounded-full", "bg-blue-600",
        ]:
            assert bad_class not in response.text, (
                f"Tailwind class '{bad_class}' found in readiness page"
            )

    def test_readiness_page_csrf_token_present(
        self, client: TestClient, seeded_db: dict
    ) -> None:
        """A CSRF token is embedded in the page when intake is ready."""
        response = client.get(f"/intakes/{seeded_db['intake_id']}/readiness")

        assert response.status_code == 200
        # A fresh DRAFT intake with no candidates is ready; CSRF token present
        assert "_csrf_token" in response.text

    def test_returns_readiness_json(self, client: TestClient, seeded_db: dict) -> None:
        """Returns JSON readiness data."""
        response = client.get(f"/intakes/{seeded_db['intake_id']}/readiness.json")

        assert response.status_code == 200
        data = response.json()
        assert data["intake_id"] == seeded_db["intake_id"]
        assert "is_ready" in data
        assert "dimensions" in data

    def test_readiness_with_no_application_link(
        self, client: TestClient, test_app, test_settings
    ) -> None:
        """Orphaned intake (no application) renders 200 without crashing."""
        # Create tables without seeding an app/intake link — just pass a random ID
        Base.metadata.create_all(test_app.state.engine)
        fake_intake_id = str(uuid.uuid4())

        # The readiness service returns a "not found" result (not an HTTP error)
        response = client.get(f"/intakes/{fake_intake_id}/readiness")
        assert response.status_code == 200


class TestFreezeEndpoint:
    """Tests for POST /intakes/{id}/freeze."""

    def test_freeze_without_csrf_returns_403(
        self, client: TestClient, seeded_db: dict
    ) -> None:
        """Freeze POST without CSRF token is rejected."""
        response = client.post(
            f"/intakes/{seeded_db['intake_id']}/freeze",
            data={},
        )
        assert response.status_code == 403

    def test_freeze_with_invalid_csrf_returns_403(
        self, client: TestClient, seeded_db: dict
    ) -> None:
        """Freeze POST with bad CSRF token is rejected."""
        response = client.post(
            f"/intakes/{seeded_db['intake_id']}/freeze",
            data={"_csrf_token": "not-a-valid-token"},
        )
        assert response.status_code == 403

    def test_freezes_intake_html(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """Freezes intake with valid CSRF and returns success page."""
        response = client.post(
            f"/intakes/{seeded_db['intake_id']}/freeze",
            data={"_csrf_token": _csrf(test_settings)},
        )

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Intake frozen" in response.text

    def test_freeze_success_has_nav(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """Freeze success page renders with nav rail."""
        response = client.post(
            f"/intakes/{seeded_db['intake_id']}/freeze",
            data={"_csrf_token": _csrf(test_settings)},
        )

        assert response.status_code == 200
        assert "<nav" in response.text

    def test_freezes_intake_json(self, client: TestClient, seeded_db: dict) -> None:
        """Freezes intake and returns JSON (JSON API has no CSRF)."""
        response = client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        assert response.status_code == 200
        data = response.json()
        assert "snapshot_id" in data
        assert data["intake_id"] == seeded_db["intake_id"]
        assert "sha256_hex" in data

    def test_freeze_is_idempotent(self, client: TestClient, seeded_db: dict) -> None:
        """Repeated freeze returns same snapshot."""
        response1 = client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")
        response2 = client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        assert data1["snapshot_id"] == data2["snapshot_id"]
        assert data2["is_new"] is False

    def test_freeze_success_has_no_tailwind(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """The success page contains no Tailwind utility class patterns."""
        response = client.post(
            f"/intakes/{seeded_db['intake_id']}/freeze",
            data={"_csrf_token": _csrf(test_settings)},
        )
        assert response.status_code == 200
        for bad_class in ["bg-green-50", "border-green-200", "text-green-800", "space-x-4"]:
            assert bad_class not in response.text, (
                f"Tailwind class '{bad_class}' found in freeze success page"
            )


class TestSnapshotEndpoint:
    """Tests for GET /intakes/{id}/snapshot."""

    def test_returns_snapshot_html(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """Returns HTML snapshot page after freeze."""
        # First freeze
        client.post(
            f"/intakes/{seeded_db['intake_id']}/freeze.json",
        )

        response = client.get(f"/intakes/{seeded_db['intake_id']}/snapshot")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Snapshot" in response.text

    def test_snapshot_has_frozen_banner(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """Snapshot page displays the read-only frozen banner."""
        client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        response = client.get(f"/intakes/{seeded_db['intake_id']}/snapshot")

        assert response.status_code == 200
        assert "read-only" in response.text
        assert "readiness-frozen-banner" in response.text

    def test_snapshot_has_nav(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """Snapshot page renders with nav rail."""
        client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        response = client.get(f"/intakes/{seeded_db['intake_id']}/snapshot")

        assert response.status_code == 200
        assert "<nav" in response.text

    def test_snapshot_has_no_tailwind(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """The snapshot page contains no Tailwind utility class patterns."""
        client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")
        response = client.get(f"/intakes/{seeded_db['intake_id']}/snapshot")

        assert response.status_code == 200
        for bad_class in ["bg-white", "shadow", "rounded-lg", "text-gray-500", "grid-cols-2"]:
            assert bad_class not in response.text, (
                f"Tailwind class '{bad_class}' found in snapshot page"
            )

    def test_snapshot_has_no_freeze_button(
        self, client: TestClient, seeded_db: dict, test_settings: Settings
    ) -> None:
        """Snapshot page does not offer a freeze action (already frozen)."""
        client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        response = client.get(f"/intakes/{seeded_db['intake_id']}/snapshot")

        assert response.status_code == 200
        # No freeze form on snapshot page
        assert 'action="/intakes/' not in response.text or "freeze" not in (
            response.text.split('action="/intakes/')[1].split('"')[0]
            if 'action="/intakes/' in response.text else ""
        )

    def test_returns_snapshot_json(self, client: TestClient, seeded_db: dict) -> None:
        """Returns JSON snapshot data after freeze."""
        # First freeze
        client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        response = client.get(f"/intakes/{seeded_db['intake_id']}/snapshot.json")

        assert response.status_code == 200
        data = response.json()
        assert data["intake_id"] == seeded_db["intake_id"]
        assert "sha256_hex" in data

    def test_returns_404_before_freeze(self, client: TestClient, seeded_db: dict) -> None:
        """Returns 404 if no snapshot exists."""
        response = client.get(f"/intakes/{seeded_db['intake_id']}/snapshot")

        assert response.status_code == 404


class TestExportEndpoint:
    """Tests for GET /intakes/{id}/export."""

    def test_exports_package(self, client: TestClient, seeded_db: dict) -> None:
        """Exports canonical package after freeze."""
        # First freeze
        client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        response = client.get(f"/intakes/{seeded_db['intake_id']}/export")

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
        assert "X-Payload-SHA256" in response.headers
        assert "X-Schema-Version" in response.headers

        # Verify it's valid JSON
        payload = response.json()
        assert "schema_version" in payload

    def test_exports_unresolved_gap_workbook(
        self, client: TestClient, seeded_db: dict, session_factory
    ) -> None:
        """Exports unresolved required questions with pinned intake metadata."""
        with session_factory() as session:
            section_id = str(uuid.uuid4())
            session.add(
                CatalogSection(
                    id=section_id,
                    release_id=seeded_db["catalog_id"],
                    section_code="SEC-1",
                    display_name="Section 1",
                    display_order=1,
                )
            )
            session.flush()
            session.add(
                CatalogQuestion(
                    id=str(uuid.uuid4()),
                    section_id=section_id,
                    question_code="Q-001",
                    question_text="What is the migration wave?",
                    response_type="TEXT",
                    required_level="REQUIRED",
                    collection_mode="MANUAL",
                    display_order=1,
                    is_active=True,
                )
            )
            session.commit()

        response = client.get(
            f"/applications/{seeded_db['app_id']}/intakes/{seeded_db['intake_id']}/gap-workbook.xlsx"
        )

        assert response.status_code == 200
        assert response.headers["x-catalog-version"] == "1.0.0"
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        rows = list(workbook.active.values)
        assert rows[0][5] == "Question Code"
        assert rows[1][5] == "Q-001"
        assert rows[1][0] == seeded_db["app_id"]
        assert rows[1][1] == seeded_db["intake_id"]

    def test_gap_workbook_rejects_other_application(
        self, client: TestClient, seeded_db: dict
    ) -> None:
        """The route cannot use an intake belonging to another application."""
        response = client.get(
            f"/applications/{uuid.uuid4()}/intakes/{seeded_db['intake_id']}/gap-workbook.xlsx"
        )

        assert response.status_code == 404

    def test_reimports_gap_workbook_as_candidate(
        self, client: TestClient, seeded_db: dict, session_factory, test_settings: Settings
    ) -> None:
        """A completed gap row is proposed, not written as a canonical answer."""
        with session_factory() as session:
            section_id = str(uuid.uuid4())
            session.add(
                CatalogSection(
                    id=section_id,
                    release_id=seeded_db["catalog_id"],
                    section_code="SEC-2",
                    display_name="Section 2",
                    display_order=1,
                )
            )
            session.flush()
            session.add(
                CatalogQuestion(
                    id=str(uuid.uuid4()),
                    section_id=section_id,
                    question_code="Q-002",
                    question_text="What is the migration wave?",
                    response_type="TEXT",
                    required_level="REQUIRED",
                    collection_mode="MANUAL",
                    display_order=1,
                    is_active=True,
                )
            )
            session.commit()

        exported = client.get(
            f"/applications/{seeded_db['app_id']}/intakes/{seeded_db['intake_id']}/gap-workbook.xlsx"
        )
        workbook = load_workbook(BytesIO(exported.content))
        sheet = workbook.active
        sheet.cell(row=2, column=12).value = "Wave 1"
        payload = BytesIO()
        workbook.save(payload)

        response = client.post(
            f"/applications/{seeded_db['app_id']}/intakes/{seeded_db['intake_id']}/gap-workbook/reimport",
            files={
                "file": (
                    "completed-gap.xlsx",
                    payload.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"_csrf_token": generate_csrf_token(test_settings.csrf_secret)},
        )

        assert response.status_code == 200
        assert response.json()["candidate_count"] == 1
        with session_factory() as session:
            candidate = session.execute(
                select(Candidate).where(Candidate.target_key == "Q-002")
            ).scalar_one()
            assert candidate.state == "PROPOSED"

    def test_reimport_rejects_stale_row_version(
        self, client: TestClient, seeded_db: dict, session_factory, test_settings: Settings
    ) -> None:
        """A stale workbook row is rejected before candidate persistence."""
        with session_factory() as session:
            section_id = str(uuid.uuid4())
            session.add(
                CatalogSection(
                    id=section_id,
                    release_id=seeded_db["catalog_id"],
                    section_code="SEC-3",
                    display_name="Section 3",
                    display_order=1,
                )
            )
            session.flush()
            session.add(
                CatalogQuestion(
                    id=str(uuid.uuid4()),
                    section_id=section_id,
                    question_code="Q-003",
                    question_text="What is the migration wave?",
                    response_type="TEXT",
                    required_level="REQUIRED",
                    collection_mode="MANUAL",
                    display_order=1,
                    is_active=True,
                )
            )
            session.commit()

        exported = client.get(
            f"/applications/{seeded_db['app_id']}/intakes/{seeded_db['intake_id']}/gap-workbook.xlsx"
        )
        workbook = load_workbook(BytesIO(exported.content))
        sheet = workbook.active
        sheet.cell(row=2, column=11).value = 1
        sheet.cell(row=2, column=12).value = "Wave 1"
        payload = BytesIO()
        workbook.save(payload)
        response = client.post(
            f"/applications/{seeded_db['app_id']}/intakes/{seeded_db['intake_id']}/gap-workbook/reimport",
            files={
                "file": (
                    "stale-gap.xlsx",
                    payload.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"_csrf_token": generate_csrf_token(test_settings.csrf_secret)},
        )

        assert response.status_code == 400
        with session_factory() as session:
            assert session.execute(select(Candidate)).scalars().all() == []

    def test_exports_manifest(self, client: TestClient, seeded_db: dict) -> None:
        """Exports manifest after freeze."""
        # First freeze
        client.post(f"/intakes/{seeded_db['intake_id']}/freeze.json")

        response = client.get(f"/intakes/{seeded_db['intake_id']}/export/manifest.json")

        assert response.status_code == 200
        data = response.json()
        assert "format_version" in data
        assert "payload_sha256" in data

    def test_returns_404_before_freeze(self, client: TestClient, seeded_db: dict) -> None:
        """Returns 404 if no snapshot exists."""
        response = client.get(f"/intakes/{seeded_db['intake_id']}/export")

        assert response.status_code == 404
