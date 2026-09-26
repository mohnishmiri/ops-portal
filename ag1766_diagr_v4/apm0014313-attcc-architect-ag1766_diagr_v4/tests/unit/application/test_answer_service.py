"""
Unit tests for AnswerService — A02.

Tests cover SaveAnswer, ClearAnswer, ConfirmAnswer, and MarkNotApplicable.
Fixtures ``tmp_engine`` and ``session_factory`` come from conftest.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from migration_intake.application.errors import (
    ClearReasonRequiredError,
    IntakeNotOpenError,
    InvalidResponseError,
    InvalidResponseTypeError,
    NoCurrentRevisionError,
    QuestionNotFoundError,
    RationaleRequiredError,
)
from migration_intake.application.services.answers import AnswerService
from migration_intake.application.dto import ActorContext
from migration_intake.persistence.models import (
    Actor,
    Application,
    AuditEvent,
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


def _seed_answer_prerequisites(engine) -> tuple[str, str, str]:
    """
    Seed the DB with the minimal rows required to exercise the answer service.

    Inserts in separate sessions per FK-dependency group so that SQLite's
    ``PRAGMA foreign_keys=ON`` is satisfied regardless of SQLAlchemy's
    internal flush order.

    Returns (actor_id, intake_id, question_id).
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
                question_code="TEST-001",
                question_text="What is your name?",
                response_type="TEXT",
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

    return actor_id, intake_id, question_id


def _seed_computed_question(
    engine, intake_id: str, section_id: str, cat_id: str
) -> str:
    """
    Seed a COMPUTED-type question in the given catalog/section.

    ``section_id`` must already exist in the DB.  Returns the new question_id.
    """
    question_id = str(uuid.uuid4())

    with Session(engine) as session:
        session.add(
            CatalogQuestion(
                id=question_id,
                section_id=section_id,
                question_code="COMPUTED-001",
                question_text="Auto-computed field",
                response_type="COMPUTED",
                required_level="OPTIONAL",
                collection_mode="SYSTEM",
                display_order=99,
                is_active=True,
            )
        )
        session.commit()

    return question_id


def _get_section_and_catalog(engine, intake_id: str) -> tuple[str, str]:
    """Return (section_id, catalog_id) for the given intake."""
    with Session(engine) as session:
        intake = session.get(Intake, intake_id)
        cat_id = str(intake.catalog_id)
        section = (
            session.query(CatalogSection)
            .filter(CatalogSection.release_id == cat_id)
            .first()
        )
        return str(section.id), cat_id


def _make_actor(actor_id: str | None = None) -> ActorContext:
    return ActorContext(
        actor_id=actor_id or str(uuid.uuid4()),
        display_name="Test Actor",
        actor_type="CONFIGURED",
    )


# ---------------------------------------------------------------------------
# Group 1 — SaveAnswer
# ---------------------------------------------------------------------------


class TestSaveAnswer:
    def test_save_answer_creates_first_revision(
        self, tmp_engine, session_factory
    ) -> None:
        """Saving a new answer creates revision_number=1 and returns changed=True."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        result = svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
        )

        assert result["changed"] is True
        assert result["revision_number"] == 1
        assert "instance_id" in result

    def test_save_answer_second_time_increments_revision(
        self, tmp_engine, session_factory
    ) -> None:
        """Saving a different value the second time produces revision_number=2."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
        )
        result = svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Bob"},
            actor=actor,
        )

        assert result["changed"] is True
        assert result["revision_number"] == 2

    def test_save_answer_semantic_noop_returns_unchanged(
        self, tmp_engine, session_factory
    ) -> None:
        """Saving the identical JSON twice returns changed=False on the second call."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        payload = {"text": "Alice"}
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json=payload,
            actor=actor,
        )
        result = svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json=payload,
            actor=actor,
        )

        assert result["changed"] is False

    def test_save_answer_writes_audit_event(
        self, tmp_engine, session_factory
    ) -> None:
        """An AuditEvent with event_code='ANSWER_SAVED' must be written to the DB."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        result = svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
        )

        instance_id = result["instance_id"]
        with Session(tmp_engine) as session:
            events = (
                session.query(AuditEvent)
                .filter(
                    AuditEvent.event_code == "ANSWER_SAVED",
                    AuditEvent.entity_type == "answer_instance",
                )
                .all()
            )
        assert len(events) >= 1
        assert str(events[0].entity_id) == instance_id

    def test_save_answer_blocked_type_raises(
        self, tmp_engine, session_factory
    ) -> None:
        """Saving a COMPUTED question raises InvalidResponseTypeError."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        section_id, cat_id = _get_section_and_catalog(tmp_engine, intake_id)
        _seed_computed_question(tmp_engine, intake_id, section_id, cat_id)

        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        with pytest.raises(InvalidResponseTypeError):
            svc.save_answer(
                intake_id=intake_id,
                question_code="COMPUTED-001",
                response_json={"value": "x"},
                actor=actor,
            )

    def test_save_answer_invalid_response_raises(
        self, tmp_engine, session_factory
    ) -> None:
        """Passing response_json=None raises InvalidResponseError."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        with pytest.raises(InvalidResponseError):
            svc.save_answer(
                intake_id=intake_id,
                question_code="TEST-001",
                response_json=None,  # type: ignore[arg-type]
                actor=actor,
            )

    def test_save_answer_closed_intake_raises(
        self, tmp_engine, session_factory
    ) -> None:
        """Saving to a FROZEN intake raises IntakeNotOpenError."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)

        # Force intake to FROZEN state
        with Session(tmp_engine) as session:
            intake = session.get(Intake, intake_id)
            intake.state = "FROZEN"
            session.commit()

        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        with pytest.raises(IntakeNotOpenError):
            svc.save_answer(
                intake_id=intake_id,
                question_code="TEST-001",
                response_json={"text": "Alice"},
                actor=actor,
            )

    def test_save_answer_unknown_question_raises(
        self, tmp_engine, session_factory
    ) -> None:
        """Saving to a nonexistent question_code raises QuestionNotFoundError."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        with pytest.raises(QuestionNotFoundError):
            svc.save_answer(
                intake_id=intake_id,
                question_code="NONEXISTENT-999",
                response_json={"text": "Alice"},
                actor=actor,
            )


# ---------------------------------------------------------------------------
# Group 2 — ClearAnswer
# ---------------------------------------------------------------------------


class TestClearAnswer:
    def test_clear_answer_creates_cleared_revision(
        self, tmp_engine, session_factory
    ) -> None:
        """Clearing a saved answer creates a new revision with confirm_state=CLEARED."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
        )
        result = svc.clear_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
        )

        assert result["changed"] is True
        assert result["revision_number"] == 2

        # Verify the revision in the DB
        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 2)
                .first()
            )
        assert rev is not None
        assert rev.confirm_state == "CLEARED"
        assert rev.response_json == {}

    def test_clear_confirmed_answer_requires_reason(
        self, tmp_engine, session_factory
    ) -> None:
        """Clearing a CONFIRMED answer without a reason raises ClearReasonRequiredError."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
        )
        svc.confirm_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            rationale="Verified by SME",
        )

        with pytest.raises(ClearReasonRequiredError):
            svc.clear_answer(
                intake_id=intake_id,
                question_code="TEST-001",
                actor=actor,
                reason="",
            )

    def test_clear_confirmed_with_reason_succeeds(
        self, tmp_engine, session_factory
    ) -> None:
        """Clearing a CONFIRMED answer with a reason succeeds and marks it CLEARED."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
        )
        svc.confirm_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            rationale="Verified by SME",
        )
        result = svc.clear_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            reason="Data was incorrect",
        )

        assert result["changed"] is True

        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 3)
                .first()
            )
        assert rev is not None
        assert rev.confirm_state == "CLEARED"


# ---------------------------------------------------------------------------
# Group 3 — ConfirmAnswer
# ---------------------------------------------------------------------------


class TestConfirmAnswer:
    def test_confirm_answer_creates_confirmed_revision(
        self, tmp_engine, session_factory
    ) -> None:
        """Confirming a saved answer creates a new revision with confirm_state=CONFIRMED."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        # TEXT type expects {"text": "..."} schema
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
        )
        result = svc.confirm_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            rationale="Verified by SME",
        )

        assert result["confirmed"] is True
        assert result["revision_number"] == 2

        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 2)
                .first()
            )
        assert rev is not None
        assert rev.confirm_state == "CONFIRMED"

    def test_confirm_carries_schema_and_evidence_lineage(
        self, tmp_engine, session_factory
    ) -> None:
        """Confirmation copies revision schema and evidence links."""
        from migration_intake.persistence.models_candidates import AnswerEvidenceLink
        from migration_intake.persistence.models_evidence import EvidenceItem
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        evidence_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)
        with Session(tmp_engine) as session:
            intake = session.query(Intake).filter_by(id=intake_id).one()
            session.add(
                EvidenceItem(
                    id=evidence_id,
                    application_id=intake.application_id,
                    intake_id=intake_id,
                    storage_key=f"synthetic/{evidence_id}",
                    sha256_hex="a" * 64,
                    size_bytes=1,
                    media_type="text/plain",
                    state="ACTIVE",
                    created_at=now,
                    created_by_id=actor_id,
                )
            )
            session.commit()

        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)
        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json={"text": "Alice"},
            actor=actor,
            response_schema_version="1.7",
        )
        with Session(tmp_engine) as session:
            instance = session.query(AnswerInstance).filter_by(intake_id=intake_id).one()
            revision = session.query(AnswerRevision).filter_by(id=instance.current_rev_id).one()
            session.add(
                AnswerEvidenceLink(
                    id=str(uuid.uuid4()),
                    revision_id=revision.id,
                    evidence_item_id=evidence_id,
                    candidate_id=None,
                    link_type="MANUAL_CITATION",
                    source_locator=None,
                    created_at=now,
                )
            )
            session.commit()

        svc.confirm_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            rationale="Verified by SME",
        )
        with Session(tmp_engine) as session:
            confirmed = session.query(AnswerRevision).filter_by(revision_number=2).one()
            links = session.query(AnswerEvidenceLink).filter_by(revision_id=confirmed.id).all()

        assert confirmed.response_schema_version == "1.7"
        assert [str(link.evidence_item_id) for link in links] == [evidence_id]

    def test_confirm_with_no_prior_revision_raises(
        self, tmp_engine, session_factory
    ) -> None:
        """Confirming before any save raises NoCurrentRevisionError."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        with pytest.raises(NoCurrentRevisionError):
            svc.confirm_answer(
                intake_id=intake_id,
                question_code="TEST-001",
                actor=actor,
                rationale="Should fail",
            )

    def test_confirm_does_not_change_response_json(
        self, tmp_engine, session_factory
    ) -> None:
        """Confirming preserves the response_json of the current revision."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)
        # Use a payload that doesn't match TEXT schema to test raw preservation
        payload = {"text": "Alice", "extra": 42}

        svc.save_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            response_json=payload,
            actor=actor,
        )
        svc.confirm_answer(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            rationale="Verified",
        )

        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 2)
                .first()
            )
        assert rev is not None
        assert rev.response_json == payload


# ---------------------------------------------------------------------------
# Group 4 — MarkNotApplicable
# ---------------------------------------------------------------------------


class TestMarkNotApplicable:
    def test_mark_not_applicable_creates_revision(
        self, tmp_engine, session_factory
    ) -> None:
        """mark_not_applicable creates a revision with confirm_state=NOT_APPLICABLE."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        result = svc.mark_not_applicable(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            rationale="Not applicable for cloud-native apps",
        )

        assert result["changed"] is True
        assert result["revision_number"] == 1

        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 1)
                .first()
            )
        assert rev is not None
        assert rev.confirm_state == "NOT_APPLICABLE"

    def test_mark_not_applicable_empty_rationale_raises(
        self, tmp_engine, session_factory
    ) -> None:
        """Calling mark_not_applicable with empty rationale raises RationaleRequiredError."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        with pytest.raises(RationaleRequiredError):
            svc.mark_not_applicable(
                intake_id=intake_id,
                question_code="TEST-001",
                actor=actor,
                rationale="",
            )

    def test_mark_not_applicable_stores_empty_response(
        self, tmp_engine, session_factory
    ) -> None:
        """mark_not_applicable stores response_json == {} in the revision."""
        actor_id, intake_id, question_id = _seed_answer_prerequisites(tmp_engine)
        svc = AnswerService(session_factory)
        actor = _make_actor(actor_id)

        svc.mark_not_applicable(
            intake_id=intake_id,
            question_code="TEST-001",
            actor=actor,
            rationale="Out of scope",
        )

        with Session(tmp_engine) as session:
            rev = (
                session.query(AnswerRevision)
                .filter(AnswerRevision.revision_number == 1)
                .first()
            )
        assert rev is not None
        assert rev.response_json == {}
