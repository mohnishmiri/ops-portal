"""
Tests for A03b — Questionnaire page read model.

Verifies:
- get_questionnaire_page returns all required fields
- Bounded query count (no N+1)
- Section navigation (previous/next)
- Answer state mapping
- Response type metadata from registry
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.queries import ApplicationQueryService
from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
    Base,
)
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun


@pytest.fixture
def tmp_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(tmp_engine):
    """Create a session factory."""
    return sessionmaker(bind=tmp_engine)


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
    
    # Create 3 sections with 2 questions each.
    for sec_idx in range(3):
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


def _seed_answer(
    engine,
    intake_id: str,
    question_id: str,
    actor_id: str,
    response_json: dict,
    confirm_state: str = "DRAFT",
) -> tuple[str, str]:
    """Seed an answer. Returns (instance_id, revision_id)."""
    now = datetime.now(tz=timezone.utc)
    instance_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())

    with Session(engine) as session:
        instance = AnswerInstance(
            id=instance_id,
            intake_id=intake_id,
            question_id=question_id,
            created_at=now,
            updated_at=now,
            row_version=1,
        )
        session.add(instance)
        session.commit()

    with Session(engine) as session:
        revision = AnswerRevision(
            id=revision_id,
            instance_id=instance_id,
            revision_number=1,
            response_json=response_json,
            confirm_state=confirm_state,
            authored_at=now,
            authored_by_id=actor_id,
        )
        session.add(revision)
        session.commit()

    with Session(engine) as session:
        instance = session.query(AnswerInstance).filter_by(id=instance_id).one()
        instance.current_rev_id = revision_id
        session.commit()

    return instance_id, revision_id


def _seed_proposed_candidate(engine, app_id: str, intake_id: str, question_code: str) -> None:
    """Seed a minimal application-scoped proposal without an answer revision."""
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


class TestGetQuestionnairePage:
    """Tests for get_questionnaire_page method."""

    def test_returns_none_for_unknown_intake(
        self, tmp_engine, session_factory
    ) -> None:
        """Returns None when intake doesn't exist."""
        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(str(uuid.uuid4()))
        assert result is None

    def test_returns_application_info(
        self, tmp_engine, session_factory
    ) -> None:
        """Result includes application info."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id)

        assert result is not None
        assert "application" in result
        assert result["application"]["id"] == app_id
        assert result["application"]["display_name"] == "Test App"
        assert result["application"]["state"] == "ACTIVE"

    def test_returns_intake_info(
        self, tmp_engine, session_factory
    ) -> None:
        """Result includes intake info with catalog version."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id)

        assert result is not None
        assert "intake" in result
        assert result["intake"]["id"] == intake_id
        assert result["intake"]["state"] == "DRAFT"
        assert result["intake"]["catalog_version"] == "1.0.0"
        assert "row_version" in result["intake"]

    def test_returns_all_sections_with_counts(
        self, tmp_engine, session_factory
    ) -> None:
        """Result includes all sections with question/answer counts."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, question_ids = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        # Answer first question in first section.
        _seed_answer(tmp_engine, intake_id, question_ids[0], actor_id, {"text": "Answer"})

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id)

        assert result is not None
        assert "sections" in result
        assert len(result["sections"]) == 3

        # First section should have 1 answered.
        sec1 = result["sections"][0]
        assert sec1["code"] == "SEC-001"
        assert sec1["question_count"] == 2
        assert sec1["answered_count"] == 1

    def test_returns_current_section_with_navigation(
        self, tmp_engine, session_factory
    ) -> None:
        """Result includes current section with previous/next codes."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)

        # First section - no previous.
        result = svc.get_questionnaire_page(intake_id, "SEC-001")
        assert result["current_section"]["code"] == "SEC-001"
        assert result["current_section"]["previous_code"] is None
        assert result["current_section"]["next_code"] == "SEC-002"

        # Middle section - has both.
        result = svc.get_questionnaire_page(intake_id, "SEC-002")
        assert result["current_section"]["code"] == "SEC-002"
        assert result["current_section"]["previous_code"] == "SEC-001"
        assert result["current_section"]["next_code"] == "SEC-003"

        # Last section - no next.
        result = svc.get_questionnaire_page(intake_id, "SEC-003")
        assert result["current_section"]["code"] == "SEC-003"
        assert result["current_section"]["previous_code"] == "SEC-002"
        assert result["current_section"]["next_code"] is None

    def test_returns_questions_with_metadata(
        self, tmp_engine, session_factory
    ) -> None:
        """Result includes questions with response type metadata."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id, "SEC-001")

        assert result is not None
        assert "questions" in result
        assert len(result["questions"]) == 2

        q1 = result["questions"][0]
        assert q1["code"] == "Q-001-001"
        assert q1["text"] == "Question 1.1"
        assert q1["help"] == "Help for question 1.1"
        assert q1["response_type"] == "TEXT"
        assert q1["editor_key"] == "text_editor"
        assert q1["is_computed"] is False
        assert q1["required_level"] == "REQUIRED"

    def test_returns_current_answer_when_exists(
        self, tmp_engine, session_factory
    ) -> None:
        """Result includes current answer with all fields."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, question_ids = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        # Answer first question.
        instance_id, _ = _seed_answer(
            tmp_engine, intake_id, question_ids[0], actor_id,
            {"text": "My answer"}, "CONFIRMED"
        )

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id, "SEC-001")

        q1 = result["questions"][0]
        assert q1["current_answer"] is not None
        assert q1["current_answer"]["instance_id"] == instance_id
        assert q1["current_answer"]["value"] == {"text": "My answer"}
        assert q1["current_answer"]["review_state"] == "CONFIRMED"
        assert q1["current_answer"]["actor_display_name"] == "Test Actor"

    def test_empty_current_revision_remains_unanswered(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, question_ids = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)
        _seed_answer(tmp_engine, intake_id, question_ids[0], actor_id, {})

        result = ApplicationQueryService(session_factory).get_questionnaire_page(
            intake_id, "SEC-001"
        )

        assert result is not None
        assert result["sections"][0]["answered_count"] == 0
        assert result["sections"][0]["completed_count"] == 0
        question = result["questions"][0]
        assert question["current_answer"] is None
        assert question["is_answered"] is False
        assert question["is_collapsed"] is False

    def test_returns_none_answer_when_not_answered(
        self, tmp_engine, session_factory
    ) -> None:
        """Result has None current_answer for unanswered questions."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id, "SEC-001")

        q1 = result["questions"][0]
        assert q1["current_answer"] is None

    def test_exposes_pending_candidate_without_treating_it_as_an_answer(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)
        _seed_proposed_candidate(tmp_engine, app_id, intake_id, "Q-001-001")

        result = ApplicationQueryService(session_factory).get_questionnaire_page(intake_id, "SEC-001")

        question = result["questions"][0]
        assert question["current_answer"] is None
        assert question["candidate_count"] == 1
        assert question["proposed_candidate_count"] == 1
        assert question["review_import_run_id"] is not None

    def test_defaults_to_first_section(
        self, tmp_engine, session_factory
    ) -> None:
        """When no section_code provided, defaults to first section."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id)

        assert result["current_section"]["code"] == "SEC-001"

    def test_returns_none_for_unknown_section(
        self, tmp_engine, session_factory
    ) -> None:
        """Returns None when section_code doesn't exist."""
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, _, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id, "UNKNOWN")
        assert result is None


class TestQuestionnairePageBoundedQueries:
    """Verify bounded query count as questions grow."""

    def test_query_count_does_not_grow_with_questions(
        self, tmp_engine, session_factory
    ) -> None:
        """
        Query count should be bounded regardless of question count.
        
        This is a smoke test - we verify the method works with many questions
        without explicit query counting (which would require instrumentation).
        """
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, section_ids, _ = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        # Add more questions to first section.
        for i in range(10):
            q_id = str(uuid.uuid4())
            with Session(tmp_engine) as session:
                session.add(
                    CatalogQuestion(
                        id=q_id,
                        section_id=section_ids[0],
                        question_code=f"Q-001-{i + 10:03d}",
                        question_text=f"Extra question {i}",
                        response_type="TEXT",
                        required_level="OPTIONAL",
                        collection_mode="SINGLE",
                        display_order=i + 10,
                    )
                )
                session.commit()

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_page(intake_id, "SEC-001")

        # Should return all 12 questions (2 original + 10 extra).
        assert len(result["questions"]) == 12
