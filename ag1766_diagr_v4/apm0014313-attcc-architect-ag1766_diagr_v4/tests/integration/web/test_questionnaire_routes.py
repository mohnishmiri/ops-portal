"""
Tests for UI04 — Questionnaire routes and section page.

Verifies:
- GET /applications/{app}/intakes/{intake}/questionnaire redirects to first section
- GET /applications/{app}/intakes/{intake}/questionnaire/{section} renders section page
- POST /applications/{app}/intakes/{intake}/questions/{code}/answer saves answer
- POST /applications/{app}/intakes/{intake}/questions/{code}/clear clears answer
- POST /applications/{app}/intakes/{intake}/questions/{code}/confirm confirms answer
- POST /applications/{app}/intakes/{intake}/questions/{code}/not-applicable marks N/A
- CSRF validation on all POST routes
- 404 for unknown intake/section
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
    CatalogOption,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
    Base,
)
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
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


def _seed_catalog_with_sections(engine) -> tuple[str, list[str], list[str]]:
    """
    Seed a catalog with multiple sections and questions.

    Returns (catalog_id, section_ids, question_ids).
    """
    now = datetime.now(tz=timezone.utc)
    cat_id = str(uuid.uuid4())

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

    section_ids = []
    question_ids = []

    # Create 2 sections with 2 questions each.
    for sec_idx in range(2):
        sec_id = str(uuid.uuid4())
        section_ids.append(sec_id)

        with Session(engine) as session:
            session.add(
                CatalogSection(
                    id=sec_id,
                    release_id=cat_id,
                    section_code=f"SEC-{sec_idx + 1:03d}",
                    display_name=f"Section {sec_idx + 1}",
                    display_order=sec_idx + 1,
                )
            )
            session.commit()

        for q_idx in range(2):
            q_id = str(uuid.uuid4())
            question_ids.append(q_id)

            with Session(engine) as session:
                session.add(
                    CatalogQuestion(
                        id=q_id,
                        section_id=sec_id,
                        question_code=f"Q-{sec_idx + 1:03d}-{q_idx + 1:03d}",
                        question_text=f"Question {sec_idx + 1}.{q_idx + 1}",
                        help_text=f"Help for question {sec_idx + 1}.{q_idx + 1}",
                        response_type="TEXT",
                        required_level="REQUIRED" if q_idx == 0 else "OPTIONAL",
                        collection_mode="SINGLE",
                        display_order=q_idx + 1,
                    )
                )
                session.commit()

    return cat_id, section_ids, question_ids


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


def _seed_proposed_candidate(engine, app_id: str, intake_id: str, question_code: str) -> str:
    """Seed a reviewable candidate without creating a canonical answer."""
    now = datetime.now(tz=timezone.utc)
    evidence_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    actor_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Import Actor", created_at=now))
        session.add(EvidenceItem(
            id=evidence_id, application_id=app_id, intake_id=intake_id,
            storage_key="evidence/test.xlsx", media_type="application/octet-stream",
            size_bytes=1, sha256_hex="b" * 64, original_filename="test.xlsx",
            state="ACTIVE", created_at=now, created_by_id=actor_id,
        ))
        session.add(ImportRun(
            id=run_id, application_id=app_id, intake_id=intake_id, evidence_item_id=evidence_id,
            contract_name="test", parser_version="1.0", state="COMPLETED",
            total_candidates=1, total_findings=0, created_at=now, completed_at=now,
            created_by_id=actor_id,
        ))
        session.flush()
        session.add(Candidate(
            id=str(uuid.uuid4()), import_run_id=run_id, application_id=app_id,
            intake_id=intake_id, evidence_item_id=evidence_id, target_kind="QUESTION",
            target_key=question_code, origin="test", extractor_version="1.0",
            contract_version="1.0", raw_value_json={"text": "Proposed"},
            scope_json={"scope": "APPLICATION"}, state="PROPOSED", row_version=1,
            created_at=now,
        ))
        session.commit()
    return run_id


class TestQuestionnaireRedirect:
    """Tests for GET /applications/{app}/intakes/{intake}/questionnaire."""

    def test_redirects_to_first_section(
        self, app, client: TestClient
    ) -> None:
        """Redirects to first section when sections exist."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/questionnaire",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/questionnaire/SEC-001" in response.headers["location"]

    def test_returns_404_for_unknown_intake(
        self, app, client: TestClient
    ) -> None:
        """Returns 404 for unknown intake."""
        response = client.get(
            f"/applications/{uuid.uuid4()}/intakes/{uuid.uuid4()}/questionnaire",
        )
        assert response.status_code == 404


class TestQuestionnaireSectionPage:
    """Tests for GET /applications/{app}/intakes/{intake}/questionnaire/{section}."""

    def test_renders_section_page(
        self, app, client: TestClient
    ) -> None:
        """Renders section page with questions."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/questionnaire/SEC-001",
        )
        assert response.status_code == 200
        assert "Section 1" in response.text
        assert "Q-001-001" in response.text
        assert "Q-001-002" in response.text

    def test_pending_candidate_is_linked_without_marking_question_answered(
        self, app, client: TestClient
    ) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)
        run_id = _seed_proposed_candidate(app.state.engine, app_id, intake_id, "Q-001-001")

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/questionnaire/SEC-001"
        )

        assert response.status_code == 200
        assert "1 pending review" in response.text
        assert f"/applications/{app_id}/intakes/{intake_id}/questionnaire" in response.text
        assert "Not answered" in response.text

    def test_contains_csrf_token(
        self, app, client: TestClient
    ) -> None:
        """Section page contains CSRF token in forms."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/questionnaire/SEC-001",
        )
        assert response.status_code == 200
        assert "_csrf_token" in response.text

    def test_contains_section_navigation(
        self, app, client: TestClient
    ) -> None:
        """Section page contains previous/next navigation."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/questionnaire/SEC-001",
        )
        assert response.status_code == 200
        assert "Next section" in response.text
        # First section has no previous
        assert "Previous section" in response.text

    def test_returns_404_for_unknown_section(
        self, app, client: TestClient
    ) -> None:
        """Returns 404 for unknown section."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.get(
            f"/applications/{app_id}/intakes/{intake_id}/questionnaire/UNKNOWN",
        )
        assert response.status_code == 404


class TestSaveAnswer:
    """Tests for POST /applications/{app}/intakes/{intake}/questions/{code}/answer."""

    def test_requires_csrf_token(
        self, app, client: TestClient
    ) -> None:
        """POST without CSRF token returns 422."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, question_ids = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/Q-001-001/answer",
            data={"text": "My answer"},
        )
        assert response.status_code == 422

    def test_rejects_invalid_csrf(
        self, app, client: TestClient
    ) -> None:
        """POST with invalid CSRF token returns 403."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/Q-001-001/answer",
            data={"_csrf_token": "invalid-token", "text": "My answer"},
        )
        assert response.status_code == 403


class TestClearAnswer:
    """Tests for POST /applications/{app}/intakes/{intake}/questions/{code}/clear."""

    def test_requires_csrf_token(
        self, app, client: TestClient
    ) -> None:
        """POST without CSRF token returns 422."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/Q-001-001/clear",
            data={},
        )
        assert response.status_code == 422


class TestConfirmAnswer:
    """Tests for POST /applications/{app}/intakes/{intake}/questions/{code}/confirm."""

    def test_requires_csrf_token(
        self, app, client: TestClient
    ) -> None:
        """POST without CSRF token returns 422."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/Q-001-001/confirm",
            data={},
        )
        assert response.status_code == 422

    def test_redirects_with_valid_csrf(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """POST with valid CSRF redirects."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/Q-001-001/confirm",
            data={"_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 303


class TestMarkNotApplicable:
    """Tests for POST /applications/{app}/intakes/{intake}/questions/{code}/not-applicable."""

    def test_requires_csrf_token(
        self, app, client: TestClient
    ) -> None:
        """POST without CSRF token returns 422."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/Q-001-001/not-applicable",
            data={},
        )
        assert response.status_code == 422

    def test_redirects_with_valid_csrf(
        self, app, client: TestClient, csrf_token: str
    ) -> None:
        """POST with valid CSRF redirects."""
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(app.state.engine)
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)

        response = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/Q-001-001/not-applicable",
            data={"_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert response.status_code == 303


class TestAnswerRoundTrip:
    """
    A saved answer must be visible again when the page reloads.

    This is the round-trip nothing previously covered, and four independent
    defects hid inside that gap at once: catalog options were never persisted
    so controlled editors rendered empty; `answer` was never put in scope for
    the editor include, so no editor could show a stored value; the
    single-select field name did not match the canonical `{value}` payload
    key the save route builds from form fields; and the form submitted the
    answer instance's row_version while AnswerService compares the current
    revision_number, so saving an existing answer always conflicted.
    """

    @staticmethod
    def _seed_single_select(engine, section_id: str) -> None:
        with Session(engine) as session:
            question_id = str(uuid.uuid4())
            session.add(
                CatalogQuestion(
                    id=question_id,
                    section_id=section_id,
                    question_code="SEL-001",
                    question_text="Pick one",
                    response_type="SINGLE_SELECT",
                    required_level="REQUIRED",
                    collection_mode="SINGLE",
                    display_order=99,
                    is_active=True,
                    response_schema_version="1.0",
                )
            )
            session.flush()
            for order, code in enumerate(("ALPHA", "BETA"), start=1):
                session.add(
                    CatalogOption(
                        id=str(uuid.uuid4()),
                        question_id=question_id,
                        option_code=code,
                        display_label=code.title(),
                        display_order=order,
                    )
                )
            session.commit()

    def test_saved_single_select_renders_selected_on_reload(
        self, app, client: TestClient
    ) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, section_ids, _ = _seed_catalog_with_sections(app.state.engine)
        self._seed_single_select(app.state.engine, section_ids[0])
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)
        csrf_token = generate_csrf_token(app.state.settings.csrf_secret)
        section_url = f"/applications/{app_id}/intakes/{intake_id}/questionnaire/SEC-001"

        # The catalog's allowed values must reach the editor at all.
        first_load = client.get(section_url)
        assert first_load.status_code == 200
        assert 'value="ALPHA"' in first_load.text
        assert 'value="BETA"' in first_load.text

        saved = client.post(
            f"/applications/{app_id}/intakes/{intake_id}/questions/SEL-001/answer",
            data={"_csrf_token": csrf_token, "_schema_version": "1.0", "value": "BETA"},
            follow_redirects=False,
        )
        assert saved.status_code == 303

        reloaded = client.get(section_url)
        block = reloaded.text.split('id="question-SEL-001"')[1].split("</form>")[0]
        assert "selected" in block, "saved answer is not pre-selected after reload"
        beta_option = block.split('value="BETA"')[1].split("</option>")[0]
        assert "selected" in beta_option

    def test_resaving_an_existing_answer_does_not_conflict(
        self, app, client: TestClient
    ) -> None:
        actor_id = app.state.settings.actor_id
        _seed_actor(app.state.engine, actor_id)
        cat_id, section_ids, _ = _seed_catalog_with_sections(app.state.engine)
        self._seed_single_select(app.state.engine, section_ids[0])
        app_id = _seed_application(app.state.engine, actor_id)
        intake_id = _seed_intake(app.state.engine, app_id, cat_id, actor_id)
        csrf_token = generate_csrf_token(app.state.settings.csrf_secret)
        answer_url = f"/applications/{app_id}/intakes/{intake_id}/questions/SEL-001/answer"
        section_url = f"/applications/{app_id}/intakes/{intake_id}/questionnaire/SEC-001"

        client.post(
            answer_url,
            data={"_csrf_token": csrf_token, "_schema_version": "1.0", "value": "ALPHA"},
            follow_redirects=False,
        )

        # Re-save using exactly the concurrency token the rendered form carries.
        block = client.get(section_url).text.split('id="question-SEL-001"')[1].split("</form>")[0]
        row_version = block.split('name="_row_version" value="')[1].split('"')[0]
        second = client.post(
            answer_url,
            data={
                "_csrf_token": csrf_token,
                "_schema_version": "1.0",
                "_row_version": row_version,
                "value": "BETA",
            },
            follow_redirects=False,
        )

        assert second.status_code == 303, f"re-save conflicted with token {row_version}"
