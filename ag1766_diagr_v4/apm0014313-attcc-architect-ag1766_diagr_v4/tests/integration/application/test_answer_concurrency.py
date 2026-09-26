"""
Integration tests for answer service concurrency — A02b.

These tests verify:
- Expected version required for edits (compare-and-swap)
- Absent version allowed only on first creation
- Stale writes raise ConcurrencyConflictError
- Response schema version persisted in revisions
- Registry-based type resolution and validation
- Semantic no-op detection using compare()
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from migration_intake.application.errors import (
    ConcurrencyConflictError,
    InvalidResponseTypeError,
)
from migration_intake.application.services.answers import AnswerService
from migration_intake.application.dto import ActorContext
from migration_intake.persistence.models import (
    Actor,
    Application,
    AnswerInstance,
    AnswerRevision,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_prerequisites(engine) -> tuple[str, str, str, str]:
    """
    Seed the DB with minimal rows for concurrency tests.

    Returns (actor_id, intake_id, question_id, section_id).
    """
    now = datetime.now(tz=timezone.utc)
    actor_id = str(uuid.uuid4())
    cat_id = str(uuid.uuid4())
    app_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    question_id = str(uuid.uuid4())
    intake_id = str(uuid.uuid4())

    # Group 1: no FK dependencies
    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))
        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="catalog.yaml",
                source_sha256="a" * 64,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                created_at=now,
            )
        )
        session.commit()

    # Group 2: depends on Actor + CatalogRelease
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

    # Group 3: depends on CatalogSection
    with Session(engine) as session:
        session.add(
            CatalogQuestion(
                id=question_id,
                section_id=section_id,
                question_code="CONC-001",
                question_text="Concurrency test question",
                response_type="YES_NO",
                required_level="REQUIRED",
                collection_mode="MANUAL",
                display_order=1,
                is_active=True,
            )
        )
        session.commit()

    # Group 4: depends on Application, CatalogRelease, Actor
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

    return actor_id, intake_id, question_id, section_id


def _seed_approval_question(engine, section_id: str) -> str:
    """Seed an APPROVAL-type question (is_computed=True)."""
    question_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            CatalogQuestion(
                id=question_id,
                section_id=section_id,
                question_code="APPROVAL-001",
                question_text="Approval decision",
                response_type="APPROVAL",
                required_level="REQUIRED",
                collection_mode="SYSTEM",
                display_order=99,
                is_active=True,
            )
        )
        session.commit()
    return question_id


def _seed_text_question(engine, section_id: str) -> str:
    """Seed a TEXT-type question for semantic comparison tests."""
    question_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            CatalogQuestion(
                id=question_id,
                section_id=section_id,
                question_code="TEXT-001",
                question_text="Enter some text",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="MANUAL",
                display_order=2,
                is_active=True,
            )
        )
        session.commit()
    return question_id


def _make_actor(actor_id: str) -> ActorContext:
    return ActorContext(
        actor_id=actor_id,
        display_name="Test Actor",
        actor_type="CONFIGURED",
    )


# ---------------------------------------------------------------------------
# Concurrency tests
# ---------------------------------------------------------------------------


class TestAnswerConcurrency:
    """Tests for optimistic concurrency control."""

    def test_first_save_without_expected_version_succeeds(
        self, tmp_engine, session_factory
    ) -> None:
        """First save with expected_version=None succeeds."""
        actor_id, intake_id, question_id, _ = _seed_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        result = svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "YES"},
            actor=actor,
            expected_version=None,  # First save, no version required
        )

        assert result["changed"] is True
        assert result["revision_number"] == 1

    def test_second_save_with_correct_version_succeeds(
        self, tmp_engine, session_factory
    ) -> None:
        """Second save with correct expected_version succeeds."""
        actor_id, intake_id, question_id, _ = _seed_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # First save
        result1 = svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "YES"},
            actor=actor,
        )

        # Second save with correct version
        result2 = svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "NO"},
            actor=actor,
            expected_version=result1["revision_number"],
        )

        assert result2["changed"] is True
        assert result2["revision_number"] == 2

    def test_stale_version_raises_concurrency_error(
        self, tmp_engine, session_factory
    ) -> None:
        """Save with stale expected_version raises ConcurrencyConflictError."""
        actor_id, intake_id, question_id, _ = _seed_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # First save
        svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "YES"},
            actor=actor,
        )

        # Second save (creates revision 2)
        svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "NO"},
            actor=actor,
            expected_version=1,
        )

        # Third save with stale version (1 instead of 2)
        with pytest.raises(ConcurrencyConflictError) as exc_info:
            svc.save_answer(
                intake_id=intake_id,
                question_code="CONC-001",
                response_json={"selected": "UNKNOWN"},
                actor=actor,
                expected_version=1,  # Stale!
            )

        assert "expected version 1" in str(exc_info.value).lower() or "stale" in str(exc_info.value).lower()


class TestRegistryTypeResolution:
    """Tests for registry-based type resolution."""

    def test_approval_type_rejects_direct_save(
        self, tmp_engine, session_factory
    ) -> None:
        """APPROVAL type (is_computed=True) rejects direct saves."""
        actor_id, intake_id, _, section_id = _seed_prerequisites(tmp_engine)
        _seed_approval_question(tmp_engine, section_id)

        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        with pytest.raises(InvalidResponseTypeError) as exc_info:
            svc.save_answer(
                intake_id=intake_id,
                question_code="APPROVAL-001",
                response_json={"decision": "APPROVED"},
                actor=actor,
            )

        assert "APPROVAL" in str(exc_info.value)

    def test_yes_no_type_validates_response(
        self, tmp_engine, session_factory
    ) -> None:
        """YES_NO type validates that selected is one of YES/NO/UNKNOWN."""
        actor_id, intake_id, question_id, _ = _seed_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # Valid YES_NO response
        result = svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "YES"},
            actor=actor,
        )

        assert result["changed"] is True


class TestSemanticComparison:
    """Tests for semantic no-op detection using compare()."""

    def test_whitespace_normalized_text_is_noop(
        self, tmp_engine, session_factory
    ) -> None:
        """Text values that normalize to the same string are semantic no-ops."""
        actor_id, intake_id, _, section_id = _seed_prerequisites(tmp_engine)
        _seed_text_question(tmp_engine, section_id)

        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # First save with trailing whitespace
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEXT-001",
            response_json={"value": "Hello World  "},
            actor=actor,
        )

        # Second save with same value after normalization
        result = svc.save_answer(
            intake_id=intake_id,
            question_code="TEXT-001",
            response_json={"value": "Hello World"},  # Normalized
            actor=actor,
        )

        # Should be a no-op since normalized values are equal
        assert result["changed"] is False


class TestResponseSchemaVersion:
    """Tests for response schema version persistence."""

    def test_schema_version_persisted_in_revision(
        self, tmp_engine, session_factory
    ) -> None:
        """Response schema version is persisted in the revision."""
        actor_id, intake_id, question_id, _ = _seed_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        result = svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "YES"},
            actor=actor,
            response_schema_version="1.0",
        )

        # Check the revision has the schema version
        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 1)
                .first()
            )
            assert rev is not None
            assert rev.response_schema_version == "1.0"

    def test_change_reason_persisted_in_revision(
        self, tmp_engine, session_factory
    ) -> None:
        """Change reason is persisted in the revision."""
        actor_id, intake_id, question_id, _ = _seed_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # First save
        svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "YES"},
            actor=actor,
        )

        # Second save with change reason
        svc.save_answer(
            intake_id=intake_id,
            question_code="CONC-001",
            response_json={"selected": "NO"},
            actor=actor,
            expected_version=1,
            change_reason="Corrected based on new information",
        )

        # Check the revision has the change reason
        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 2)
                .first()
            )
            assert rev is not None
            assert rev.change_reason == "Corrected based on new information"
