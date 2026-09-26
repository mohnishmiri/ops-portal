"""
Tests for UI05 — Evidence routes (sources, upload, import summary).

Verifies:
- GET /applications/{app}/intakes/{intake}/sources lists evidence
- GET /applications/{app}/intakes/{intake}/imports/{run} shows import details
- GET /applications/{app}/intakes/{intake}/imports/{run}/diagnostics.csv exports CSV
- CSRF validation on all POST routes
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.models import (
    Actor,
    AnswerRevision,
    Application,
    Base,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_candidates import AnswerEvidenceLink, Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportFinding, ImportRun, ImportSheetResult
from migration_intake.storage.filesystem import FilesystemStore
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
        csrf_secret="test-csrf-secret-key-12345",  # noqa: S106 - test fixture, not a secret
    )


@pytest.fixture
def app(settings: Settings):
    """Create test app with database tables."""
    # Import all models
    import migration_intake.persistence.models_candidates
    import migration_intake.persistence.models_imports  # noqa: F401

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
    now = datetime.now(tz=UTC)
    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))
        session.commit()


def _seed_application(engine, actor_id: str) -> str:
    """Seed an application. Returns application_id."""
    now = datetime.now(tz=UTC)
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
    now = datetime.now(tz=UTC)
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
    now = datetime.now(tz=UTC)
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


def _seed_catalog_question(engine, catalog_id: str, question_code: str) -> str:
    """Seed one active TEXT question for candidate acceptance tests."""
    section_id = str(uuid.uuid4())
    question_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            CatalogSection(
                id=section_id,
                release_id=catalog_id,
                # One section per question keeps repeated calls from colliding
                # on the release's unique section code.
                section_code=f"SEC-{question_code}",
                display_name="Application",
                display_order=1,
            )
        )
        session.flush()
        session.add(
            CatalogQuestion(
                id=question_id,
                section_id=section_id,
                question_code=question_code,
                question_text="Synthetic application status",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="SINGLE",
                display_order=1,
            )
        )
        session.commit()
    return question_id


def _seed_evidence(
    engine, app_id: str, intake_id: str, actor_id: str, evidence_root: Path | None = None
) -> str:
    """Seed an evidence item. Returns evidence_id."""
    now = datetime.now(tz=UTC)
    evidence_id = str(uuid.uuid4())
    storage_key = f"evidence/{evidence_id}/test.xlsx"
    if evidence_root is not None:
        from openpyxl import Workbook

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Control ID", "Response"])
        worksheet.append(["APP-001", "Example"])
        stream = BytesIO()
        workbook.save(stream)
        storage_key = FilesystemStore(evidence_root).store(stream, "test.xlsx").storage_key

    with Session(engine) as session:
        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=app_id,
                intake_id=intake_id,
                storage_key=storage_key,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes=1024,
                sha256_hex="b" * 64,
                original_filename="test.xlsx",
                state="ACTIVE",
                created_at=now,
                created_by_id=actor_id,
            )
        )
        session.commit()

    return evidence_id


def _seed_import_run(
    engine, app_id: str, intake_id: str, evidence_id: str, actor_id: str
) -> str:
    """Seed an import run. Returns run_id."""
    now = datetime.now(tz=UTC)
    run_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            ImportRun(
                id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                contract_name="APP_DATA_CAPTURE_V1",
                parser_version="1.0.0",
                state="COMPLETED",
                total_sheets=2,
                total_candidates=5,
                total_findings=1,
                identity_decision="APPLICATION_MATCHED",
                created_at=now,
                completed_at=now,
                created_by_id=actor_id,
            )
        )
        session.commit()

    return run_id


def _seed_sheet_result(engine, run_id: str) -> str:
    """Seed a sheet result. Returns result_id."""
    result_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            ImportSheetResult(
                id=result_id,
                run_id=run_id,
                sheet_name="TSS",
                outcome="VALID",
                candidate_count=3,
                finding_count=0,
            )
        )
        session.commit()

    return result_id


def _seed_finding(engine, run_id: str) -> str:
    """Seed a finding. Returns finding_id."""
    finding_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            ImportFinding(
                id=finding_id,
                run_id=run_id,
                sheet_name="App",
                finding_type="VALIDATION_WARNING",
                severity="WARNING",
                source_locator="Sheet:App/Row:5",
                detail="Value may be outdated",
            )
        )
        session.commit()

    return finding_id


def _seed_candidate(
    engine,
    run_id: str,
    app_id: str,
    intake_id: str,
    evidence_id: str,
    target_key: str = "APP-003",
) -> str:
    """Seed one reviewable candidate with source provenance."""
    candidate_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            Candidate(
                id=candidate_id,
                import_run_id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_id,
                target_kind="QUESTION",
                target_key=target_key,
                origin="uaq-v1",
                extractor_version="1.0",
                contract_version="uaq-v1",
                source_locator={"sheet": "UAQ", "column": "INV9"},
                raw_value_json={"value": "active"},
                normalized_value_json={"value": "ACTIVE"},
                scope_json={"scope": "APPLICATION"},
                validation_json={"outcome": "VALID"},
                state="PROPOSED",
                row_version=1,
                created_at=datetime.now(tz=UTC),
            )
        )
        session.commit()
    return candidate_id


class TestListSources:
    """Tests for GET /applications/{app}/intakes/{intake}/sources."""

    def test_renders_sources_page(self, app, client: TestClient) -> None:
        """Renders sources page."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/sources"
        )

        assert response.status_code == 200
        assert "Evidence Sources" in response.text

    def test_shows_uploaded_evidence(self, app, client: TestClient) -> None:
        """Shows uploaded evidence items."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        _seed_evidence(app.state.engine, app_id, intake_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/sources"
        )

        assert response.status_code == 200
        assert "test.xlsx" in response.text

    def test_only_legacy_intake_upload_is_discoverable(
        self, app, client: TestClient
    ) -> None:
        """The sources page exposes only the legacy intake upload lane."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(f"/applications/{app_id}/intakes/{intake_id}/sources")
        legacy_upload_action = (
            f"/applications/{app_id}/intakes/{intake_id}/legacy-intake/upload"
        )

        assert response.status_code == 200
        assert f'action="{legacy_upload_action}"' in response.text
        assert "Source documents" not in response.text
        assert "Intake form" not in response.text

    def test_shows_import_status(self, app, client: TestClient) -> None:
        """Shows import status for processed evidence."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(
            app.state.engine, app_id, intake_id, actor_id, Path(app.state.settings.evidence_root)
        )
        _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/sources"
        )

        assert response.status_code == 200
        assert "Processed" in response.text or "COMPLETED" in response.text

    def test_review_button_omits_redundant_proposal_count(
        self, app, client: TestClient
    ) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(
            app.state.engine,
            app_id,
            intake_id,
            actor_id,
            Path(app.state.settings.evidence_root),
        )
        run_id = _seed_import_run(
            app.state.engine, app_id, intake_id, evidence_id, actor_id
        )
        _seed_candidate(app.state.engine, run_id, app_id, intake_id, evidence_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/sources"
        )

        assert response.status_code == 200
        assert "<strong>1 proposal</strong>" in response.text
        assert ">Review →</a>" in response.text
        assert "Review 1" not in response.text


class TestImportDetail:
    """Tests for GET /applications/{app}/intakes/{intake}/imports/{run}."""

    def test_renders_import_detail(self, app, client: TestClient) -> None:
        """Renders import detail page."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}"
        )

        assert response.status_code == 200
        assert "Import Run Details" in response.text
        assert "Review extracted data" in response.text

    def test_shows_sheet_results(self, app, client: TestClient) -> None:
        """Shows sheet results."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        _seed_sheet_result(app.state.engine, run_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}"
        )

        assert response.status_code == 200
        assert "TSS" in response.text

    def test_shows_findings(self, app, client: TestClient) -> None:
        """Shows findings."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        _seed_finding(app.state.engine, run_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}"
        )

        assert response.status_code == 200
        assert "VALIDATION_WARNING" in response.text

    def test_returns_404_for_unknown_run(self, app, client: TestClient) -> None:
        """Returns 404 for unknown run."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{uuid.uuid4()}"
        )

        assert response.status_code == 404


class TestImportCoverage:
    """Tests for GET /applications/{app}/intakes/{intake}/imports/{run}/coverage."""

    def test_renders_read_only_coverage(self, app, client: TestClient) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        _seed_candidate(app.state.engine, run_id, app_id, intake_id, evidence_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}/coverage"
        )

        assert response.status_code == 200
        assert "Review extracted data" in response.text
        assert "APPLICATION_MATCHED" in response.text
        assert "Required" in response.text
        assert ">0</td>" in response.text
        assert "APP-003" in response.text
        assert "APPLICATION" in response.text
        assert "ACTIVE" in response.text

    def test_returns_404_for_wrong_application_or_intake(self, app, client: TestClient) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)

        response = client.get(
            f"/applications/{uuid.uuid4()}/intakes/{intake_id}/imports/{run_id}/coverage"
        )

        assert response.status_code == 404


class TestImportCandidateDecisions:
    """Tests for identity-gated candidate decisions from import coverage."""

    def test_accept_creates_one_revision_and_evidence_link(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        _seed_catalog_question(app.state.engine, catalog_id, "APP-003")
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        candidate_id = _seed_candidate(app.state.engine, run_id, app_id, intake_id, evidence_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}/candidates/{candidate_id}/accept",
            data={"_csrf_token": csrf_token, "_row_version": "1"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with Session(app.state.engine) as session:
            candidate = session.get(Candidate, candidate_id)
            revisions = list(session.execute(select(AnswerRevision)).scalars())
            links = list(session.execute(select(AnswerEvidenceLink)).scalars())
        assert candidate.state == "ACCEPTED"
        assert len(revisions) == 1
        assert len(links) == 1
        assert str(links[0].candidate_id) == candidate_id

    @pytest.mark.parametrize("decision", ["reject", "defer"])
    def test_non_acceptance_does_not_create_canonical_answer(
        self, app, client: TestClient, csrf_token: str, decision: str
    ) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        _seed_catalog_question(app.state.engine, catalog_id, "APP-003")
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        candidate_id = _seed_candidate(app.state.engine, run_id, app_id, intake_id, evidence_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}/candidates/{candidate_id}/{decision}",
            data={"_csrf_token": csrf_token, "_row_version": "1", "reason": "Needs follow-up"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        with Session(app.state.engine) as session:
            candidate = session.get(Candidate, candidate_id)
            revisions = list(session.execute(select(AnswerRevision)).scalars())
        assert candidate.state == {"reject": "REJECTED", "defer": "DEFERRED"}[decision]
        assert revisions == []


class TestBulkCandidateDecisions:
    """
    Tests for POST .../imports/{run}/candidates/bulk.

    Clearing a 17-proposal import used to cost 17 page round-trips. Bulk
    decisions drive the same ``CandidateService`` per candidate, so the batch
    must report per-row outcomes rather than succeed or fail as a whole.
    """

    def _seeded(self, app, *, codes: tuple[str, ...]) -> dict:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        for code in codes:
            _seed_catalog_question(app.state.engine, catalog_id, code)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        candidates = {
            code: _seed_candidate(
                app.state.engine, run_id, app_id, intake_id, evidence_id, target_key=code
            )
            for code in codes
        }
        return {
            "app_id": app_id,
            "intake_id": intake_id,
            "run_id": run_id,
            "candidates": candidates,
        }

    def test_accepts_every_selected_candidate_in_one_request(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        seeded = self._seeded(app, codes=("APP-003", "APP-005", "APP-007"))

        response = client.post(
            f"/applications/{seeded['app_id']}/intakes/{seeded['intake_id']}"
            f"/imports/{seeded['run_id']}/candidates/bulk",
            data={
                "_csrf_token": csrf_token,
                "decision": "accept",
                "selected": [
                    f"{candidate_id}:1" for candidate_id in seeded["candidates"].values()
                ],
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "bulk_message=3+accepted." in response.headers["location"]
        with Session(app.state.engine) as session:
            revisions = list(session.execute(select(AnswerRevision)).scalars())
            states = {
                session.get(Candidate, candidate_id).state
                for candidate_id in seeded["candidates"].values()
            }
        assert len(revisions) == 3
        assert states == {"ACCEPTED"}

    def test_reports_partial_result_when_one_candidate_is_stale(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """A row version from a page loaded before another decision must not
        silently fail the batch, nor claim a success it did not achieve."""
        seeded = self._seeded(app, codes=("APP-003", "APP-005"))
        stale_id = seeded["candidates"]["APP-003"]

        response = client.post(
            f"/applications/{seeded['app_id']}/intakes/{seeded['intake_id']}"
            f"/imports/{seeded['run_id']}/candidates/bulk",
            data={
                "_csrf_token": csrf_token,
                "decision": "accept",
                "selected": [
                    f"{stale_id}:99",
                    f"{seeded['candidates']['APP-005']}:1",
                ],
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        location = response.headers["location"]
        assert "bulk_message=1+accepted%2C+1+skipped." in location
        assert "APP-003" in location
        assert "stale" in location
        with Session(app.state.engine) as session:
            assert session.get(Candidate, stale_id).state == "PROPOSED"
            assert len(list(session.execute(select(AnswerRevision)).scalars())) == 1

    def test_rejecting_without_a_reason_changes_nothing(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        seeded = self._seeded(app, codes=("APP-003",))

        response = client.post(
            f"/applications/{seeded['app_id']}/intakes/{seeded['intake_id']}"
            f"/imports/{seeded['run_id']}/candidates/bulk",
            data={
                "_csrf_token": csrf_token,
                "decision": "reject",
                "selected": [f"{seeded['candidates']['APP-003']}:1"],
                "reason": "   ",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "Rejecting+requires+a+reason" in response.headers["location"]
        with Session(app.state.engine) as session:
            assert session.get(Candidate, seeded["candidates"]["APP-003"]).state == "PROPOSED"

    def test_rejects_selected_candidates_without_writing_answers(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        seeded = self._seeded(app, codes=("APP-003", "APP-005"))

        response = client.post(
            f"/applications/{seeded['app_id']}/intakes/{seeded['intake_id']}"
            f"/imports/{seeded['run_id']}/candidates/bulk",
            data={
                "_csrf_token": csrf_token,
                "decision": "reject",
                "selected": [
                    f"{candidate_id}:1" for candidate_id in seeded["candidates"].values()
                ],
                "reason": "Superseded by the interface register",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "bulk_message=2+rejected." in response.headers["location"]
        with Session(app.state.engine) as session:
            states = {
                session.get(Candidate, candidate_id).state
                for candidate_id in seeded["candidates"].values()
            }
            assert list(session.execute(select(AnswerRevision)).scalars()) == []
        assert states == {"REJECTED"}

    def test_empty_selection_is_reported_not_silently_successful(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        seeded = self._seeded(app, codes=("APP-003",))

        response = client.post(
            f"/applications/{seeded['app_id']}/intakes/{seeded['intake_id']}"
            f"/imports/{seeded['run_id']}/candidates/bulk",
            data={"_csrf_token": csrf_token, "decision": "accept"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "Nothing+was+selected" in response.headers["location"]

    def test_rejects_invalid_csrf(self, app, client: TestClient) -> None:
        seeded = self._seeded(app, codes=("APP-003",))

        response = client.post(
            f"/applications/{seeded['app_id']}/intakes/{seeded['intake_id']}"
            f"/imports/{seeded['run_id']}/candidates/bulk",
            data={"_csrf_token": "invalid", "decision": "accept"},
        )

        assert response.status_code == 403


class TestSourcesLanes:
    """The sources page exposes only the legacy intake upload lane."""

    def _seeded(self, app) -> tuple[str, str]:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        return app_id, intake_id

    def test_renders_only_legacy_intake_lane(self, app, client: TestClient) -> None:
        app_id, intake_id = self._seeded(app)

        response = client.get(f"/applications/{app_id}/intakes/{intake_id}/sources")

        assert response.status_code == 200
        assert "lane-card--legacy" in response.text
        assert "Legacy intake" in response.text
        assert "lane-card--source" not in response.text
        assert "lane-card--form" not in response.text

    def test_quarantined_import_explains_the_mismatch_and_how_to_fix(
        self, app, client: TestClient
    ) -> None:
        """A quarantined row used to end in a dead end that blamed the
        application record; it must name the identifier and offer a way out."""
        actor_id = app.state.settings.actor_id
        app_id, intake_id = self._seeded(app)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        with Session(app.state.engine) as session:
            run = session.get(ImportRun, run_id)
            run.identity_decision = "APPLICATION_MISMATCH"
            run.source_identity_raw = "99999"
            session.commit()

        response = client.get(f"/applications/{app_id}/intakes/{intake_id}/sources")

        assert response.status_code == 200
        assert "import-row--quarantined" in response.text
        assert "Quarantined" in response.text
        assert "99999" in response.text
        assert "How to fix" in response.text


class TestDiagnosticsCsv:
    """Tests for GET /applications/{app}/intakes/{intake}/imports/{run}/diagnostics.csv."""

    def test_returns_csv(self, app, client: TestClient) -> None:
        """Returns CSV file."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}/diagnostics.csv"
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]

    def test_csv_contains_findings(self, app, client: TestClient) -> None:
        """CSV contains findings data."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)
        evidence_id = _seed_evidence(app.state.engine, app_id, intake_id, actor_id)
        run_id = _seed_import_run(app.state.engine, app_id, intake_id, evidence_id, actor_id)
        _seed_finding(app.state.engine, run_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{run_id}/diagnostics.csv"
        )

        assert response.status_code == 200
        content = response.text
        assert "VALIDATION_WARNING" in content
        assert "WARNING" in content

    def test_returns_404_for_unknown_run(self, app, client: TestClient) -> None:
        """Returns 404 for unknown run."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        catalog_id = _seed_catalog(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, catalog_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/imports/{uuid.uuid4()}/diagnostics.csv"
        )

        assert response.status_code == 404
