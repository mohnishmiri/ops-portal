"""
Unit tests for SnapshotService — A05.

Verifies:
- Freeze creates immutable snapshot
- Freeze transitions intake to FROZEN
- Freeze is idempotent (repeated freeze returns existing snapshot)
- Not ready intake raises IntakeNotReadyError
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    Intake,
    Base,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.application.services.snapshots import (
    SnapshotService,
    IntakeNotReadyError,
)
from migration_intake.application.dto import ActorContext


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


@pytest.fixture
def service(session_factory) -> SnapshotService:
    """Create a SnapshotService instance."""
    return SnapshotService(session_factory)


@pytest.fixture
def actor_context() -> ActorContext:
    """Create an actor context for testing."""
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
    )


def _seed_prerequisites(session_factory, actor_id: str) -> dict:
    """Seed prerequisite records."""
    now = datetime.now(tz=timezone.utc)

    with session_factory() as session:
        # Actor
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


def _create_proposed_candidate(session_factory, prereqs: dict) -> str:
    """Create a PROPOSED candidate and return its ID."""
    now = datetime.now(tz=timezone.utc)
    candidate_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with session_factory() as session:
        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=prereqs["app_id"],
                intake_id=prereqs["intake_id"],
                storage_key=f"evidence/{evidence_id}/test.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes=1024,
                sha256_hex="b" * 64,
                original_filename="test.xlsx",
                state="ACTIVE",
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
        )
        session.flush()

        session.add(
            ImportRun(
                id=run_id,
                application_id=prereqs["app_id"],
                intake_id=prereqs["intake_id"],
                evidence_item_id=evidence_id,
                contract_name="TEST_V1",
                parser_version="1.0.0",
                state="COMPLETED",
                created_at=now,
                created_by_id=prereqs["actor_id"],
            )
        )
        session.flush()

        session.add(
            Candidate(
                id=candidate_id,
                import_run_id=run_id,
                application_id=prereqs["app_id"],
                intake_id=prereqs["intake_id"],
                evidence_item_id=evidence_id,
                target_kind="TEST",
                target_key="test-key",
                origin="test",
                extractor_version="1.0.0",
                contract_version="TEST_V1",
                raw_value_json={"test": "value"},
                state="PROPOSED",
                row_version=1,
                created_at=now,
            )
        )
        session.commit()

    return candidate_id


class TestFreezeIntake:
    """Tests for freeze_intake."""

    def test_creates_snapshot(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Freeze creates an immutable snapshot."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        result = service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        assert result.snapshot_id is not None
        assert result.intake_id == prereqs["intake_id"]
        assert result.sha256_hex is not None
        assert result.is_new is True

    def test_transitions_intake_to_frozen(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Freeze transitions intake to FROZEN state."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        # Verify intake state
        with session_factory() as session:
            intake = session.get(Intake, prereqs["intake_id"])
            assert intake.state == "FROZEN"

    def test_snapshot_persisted(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Snapshot is persisted to database."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        result = service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        # Verify snapshot in database
        with session_factory() as session:
            repo = SnapshotRepository(session)
            snapshot = repo.get_by_id(result.snapshot_id)
            assert snapshot is not None
            assert snapshot["sha256_hex"] == result.sha256_hex

    def test_failed_intake_cas_rolls_back_snapshot(
        self, session_factory, service: SnapshotService, actor_context: ActorContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed intake state CAS leaves no committed snapshot."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        def reject_update(*_args, **_kwargs):
            return False

        monkeypatch.setattr(
            "migration_intake.application.services.snapshots.IntakeRepository.update_state",
            reject_update,
        )

        from migration_intake.application.errors import ConcurrencyConflictError

        with pytest.raises(ConcurrencyConflictError):
            service.freeze_intake(
                prereqs["intake_id"],
                actor_context,
                skip_readiness_check=True,
            )

        assert service.get_snapshot(prereqs["intake_id"]) is None


class TestIdempotentFreeze:
    """Tests for idempotent freeze behavior."""

    def test_repeated_freeze_returns_existing_snapshot(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Repeated freeze returns existing snapshot."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        # First freeze
        result1 = service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        # Second freeze (should be idempotent)
        result2 = service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        assert result2.snapshot_id == result1.snapshot_id
        assert result2.sha256_hex == result1.sha256_hex
        assert result2.is_new is False


class TestReadinessCheck:
    """Tests for readiness check during freeze."""

    def test_not_ready_raises_error(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Not ready intake raises IntakeNotReadyError."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)
        _create_proposed_candidate(session_factory, prereqs)

        with pytest.raises(IntakeNotReadyError) as exc_info:
            service.freeze_intake(prereqs["intake_id"], actor_context)

        assert exc_info.value.readiness.is_ready is False


class TestGetSnapshot:
    """Tests for get_snapshot."""

    def test_returns_snapshot_after_freeze(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Returns snapshot after freeze."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        snapshot = service.get_snapshot(prereqs["intake_id"])

        assert snapshot is not None
        assert snapshot["intake_id"] == prereqs["intake_id"]

    def test_returns_none_before_freeze(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Returns None before freeze."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        snapshot = service.get_snapshot(prereqs["intake_id"])

        assert snapshot is None


class TestCanonicalAnswersInSnapshot:
    """Tests for P3: confirmed answers in snapshots."""

    def test_confirmed_answer_appears_in_snapshot(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Confirmed answers appear in the canonical snapshot."""
        import json
        from migration_intake.persistence.models import (
            CatalogSection,
            CatalogQuestion,
            AnswerInstance,
            AnswerRevision,
        )

        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)
        now = datetime.now(tz=timezone.utc)

        # Create a catalog section and question
        section_id = str(uuid.uuid4())
        question_id = str(uuid.uuid4())
        instance_id = str(uuid.uuid4())
        revision_id = str(uuid.uuid4())

        with session_factory() as session:
            # Add section
            session.add(
                CatalogSection(
                    id=section_id,
                    release_id=prereqs["catalog_id"],
                    section_code="CTL",
                    display_name="Control",
                    display_order=1,
                )
            )
            session.flush()

            # Add question
            session.add(
                CatalogQuestion(
                    id=question_id,
                    section_id=section_id,
                    question_code="CTL-002",
                    question_text="Application Name and Acronym",
                    response_type="TEXT_PAIR",
                    required_level="REQUIRED",
                    collection_mode="MANUAL",
                    display_order=1,
                )
            )
            session.flush()

            # Add answer instance
            session.add(
                AnswerInstance(
                    id=instance_id,
                    intake_id=prereqs["intake_id"],
                    question_id=question_id,
                    created_at=now,
                    current_rev_id=None,
                    applicability="APPLICABLE",
                    value_state="ANSWERED",
                    review_state="REVIEWED",
                    updated_at=now,
                    row_version=1,
                )
            )
            session.flush()

            # Add confirmed revision
            session.add(
                AnswerRevision(
                    id=revision_id,
                    instance_id=instance_id,
                    revision_number=1,
                    response_json={"first": "Test App", "second": "TA"},
                    confirm_state="CONFIRMED",
                    authored_at=now,
                    authored_by_id=prereqs["actor_id"],
                    response_schema_version="1.0",
                )
            )
            session.flush()

            # Update instance to point to revision
            instance = session.get(AnswerInstance, instance_id)
            instance.current_rev_id = revision_id
            session.commit()

        # Freeze the intake
        result = service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        # Get the snapshot and verify the answer is included
        snapshot = service.get_snapshot(prereqs["intake_id"])
        assert snapshot is not None

        canonical_json = snapshot["canonical_json"]
        parsed = json.loads(canonical_json)

        # Verify schema version is 2.0.0
        assert parsed["schema_version"] == "2.0.0"

        # Verify the confirmed answer is included
        assert len(parsed["answers"]) == 1
        answer = parsed["answers"][0]
        assert answer["question_code"] == "CTL-002"
        assert answer["section_code"] == "CTL"
        assert answer["response_type"] == "TEXT_PAIR"
        assert answer["value"] == {"first": "Test App", "second": "TA"}
        assert answer["confirm_state"] == "CONFIRMED"
        assert answer["revision_number"] == 1

    def test_unconfirmed_answer_excluded_from_snapshot(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Unconfirmed (DRAFT) answers are excluded from the canonical snapshot."""
        import json
        from migration_intake.persistence.models import (
            CatalogSection,
            CatalogQuestion,
            AnswerInstance,
            AnswerRevision,
        )

        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)
        now = datetime.now(tz=timezone.utc)

        # Create a catalog section and question
        section_id = str(uuid.uuid4())
        question_id = str(uuid.uuid4())
        instance_id = str(uuid.uuid4())
        revision_id = str(uuid.uuid4())

        with session_factory() as session:
            # Add section
            session.add(
                CatalogSection(
                    id=section_id,
                    release_id=prereqs["catalog_id"],
                    section_code="CTL",
                    display_name="Control",
                    display_order=1,
                )
            )
            session.flush()

            # Add question
            session.add(
                CatalogQuestion(
                    id=question_id,
                    section_id=section_id,
                    question_code="CTL-002",
                    question_text="Application Name and Acronym",
                    response_type="TEXT_PAIR",
                    required_level="REQUIRED",
                    collection_mode="MANUAL",
                    display_order=1,
                )
            )
            session.flush()

            # Add answer instance
            session.add(
                AnswerInstance(
                    id=instance_id,
                    intake_id=prereqs["intake_id"],
                    question_id=question_id,
                    created_at=now,
                    current_rev_id=None,
                    applicability="APPLICABLE",
                    value_state="ANSWERED",
                    review_state="UNREVIEWED",
                    updated_at=now,
                    row_version=1,
                )
            )
            session.flush()

            # Add DRAFT revision (not confirmed)
            session.add(
                AnswerRevision(
                    id=revision_id,
                    instance_id=instance_id,
                    revision_number=1,
                    response_json={"first": "Draft App", "second": "DA"},
                    confirm_state="DRAFT",  # Not confirmed
                    authored_at=now,
                    authored_by_id=prereqs["actor_id"],
                )
            )
            session.flush()

            # Update instance to point to revision
            instance = session.get(AnswerInstance, instance_id)
            instance.current_rev_id = revision_id
            session.commit()

        # Freeze the intake
        result = service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        # Get the snapshot and verify the draft answer is excluded
        snapshot = service.get_snapshot(prereqs["intake_id"])
        assert snapshot is not None

        canonical_json = snapshot["canonical_json"]
        parsed = json.loads(canonical_json)

        # Verify no answers are included (draft excluded)
        assert len(parsed["answers"]) == 0

    def test_snapshot_schema_version_is_2_0_0(
        self, session_factory, service: SnapshotService, actor_context: ActorContext
    ) -> None:
        """Snapshot uses schema version 2.0.0."""
        import json

        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        snapshot = service.get_snapshot(prereqs["intake_id"])
        assert snapshot is not None

        canonical_json = snapshot["canonical_json"]
        parsed = json.loads(canonical_json)

        assert parsed["schema_version"] == "2.0.0"
        assert "identifiers" in parsed["application"]
        assert "target_resources" in parsed
        assert "catalog_hash" in parsed["catalog"]
