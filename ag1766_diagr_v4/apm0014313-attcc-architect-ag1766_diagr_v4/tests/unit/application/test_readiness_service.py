"""
Unit tests for ReadinessService — A05.

Verifies:
- Readiness is a structured result with dimensions
- Unresolved candidates block freeze
- Deferred candidates are permitted
- Already frozen intakes are ready
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
from migration_intake.application.services.readiness import ReadinessService


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
def service(session_factory) -> ReadinessService:
    """Create a ReadinessService instance."""
    return ReadinessService(session_factory)


def _seed_prerequisites(session_factory) -> dict:
    """Seed prerequisite records."""
    now = datetime.now(tz=timezone.utc)

    with session_factory() as session:
        # Actor
        actor_id = str(uuid.uuid4())
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


def _create_candidate(session_factory, prereqs: dict, state: str = "PROPOSED") -> str:
    """Create a candidate and return its ID."""
    now = datetime.now(tz=timezone.utc)
    candidate_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with session_factory() as session:
        # Evidence
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

        # Import run
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

        # Candidate
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
                state=state,
                row_version=1,
                created_at=now,
            )
        )
        session.commit()

    return candidate_id


class TestReadinessResult:
    """Tests for readiness result structure."""

    def test_returns_structured_result(
        self, session_factory, service: ReadinessService
    ) -> None:
        """Returns a structured result with dimensions."""
        prereqs = _seed_prerequisites(session_factory)

        result = service.check_readiness(prereqs["intake_id"])

        assert result.intake_id == prereqs["intake_id"]
        assert isinstance(result.dimensions, list)
        assert len(result.dimensions) > 0
        assert result.checked_at is not None

    def test_intake_not_found(self, session_factory, service: ReadinessService) -> None:
        """Returns not ready for non-existent intake."""
        result = service.check_readiness(str(uuid.uuid4()))

        assert result.is_ready is False
        assert any(d.name == "intake_exists" for d in result.dimensions)


class TestUnresolvedCandidates:
    """Tests for unresolved candidates dimension."""

    def test_unresolved_candidates_block_freeze(
        self, session_factory, service: ReadinessService
    ) -> None:
        """Unresolved candidates block freeze."""
        prereqs = _seed_prerequisites(session_factory)
        _create_candidate(session_factory, prereqs, state="PROPOSED")

        result = service.check_readiness(prereqs["intake_id"])

        assert result.is_ready is False
        unresolved_dim = next(
            d for d in result.dimensions if d.name == "unresolved_candidates"
        )
        assert unresolved_dim.passed is False
        assert len(unresolved_dim.blockers) > 0

    def test_no_unresolved_candidates_passes(
        self, session_factory, service: ReadinessService
    ) -> None:
        """No unresolved candidates passes dimension."""
        prereqs = _seed_prerequisites(session_factory)

        result = service.check_readiness(prereqs["intake_id"])

        unresolved_dim = next(
            d for d in result.dimensions if d.name == "unresolved_candidates"
        )
        assert unresolved_dim.passed is True


class TestDeferredCandidates:
    """Tests for deferred candidates dimension."""

    def test_deferred_candidates_permitted(
        self, session_factory, service: ReadinessService
    ) -> None:
        """Deferred candidates are permitted (not blocking)."""
        prereqs = _seed_prerequisites(session_factory)
        _create_candidate(session_factory, prereqs, state="DEFERRED")

        result = service.check_readiness(prereqs["intake_id"])

        deferred_dim = next(
            d for d in result.dimensions if d.name == "deferred_candidates"
        )
        assert deferred_dim.passed is True


class TestIntakeState:
    """Tests for intake state dimension."""

    def test_draft_state_allowed(
        self, session_factory, service: ReadinessService
    ) -> None:
        """DRAFT state is allowed for freeze."""
        prereqs = _seed_prerequisites(session_factory)

        result = service.check_readiness(prereqs["intake_id"])

        state_dim = next(d for d in result.dimensions if d.name == "intake_state")
        assert state_dim.passed is True

    def test_frozen_state_is_ready(self, session_factory, service: ReadinessService) -> None:
        """FROZEN state returns ready (idempotent)."""
        prereqs = _seed_prerequisites(session_factory)

        # Update intake to FROZEN
        with session_factory() as session:
            from migration_intake.persistence.models import Intake
            intake = session.get(Intake, prereqs["intake_id"])
            intake.state = "FROZEN"
            session.commit()

        result = service.check_readiness(prereqs["intake_id"])

        assert result.is_ready is True
