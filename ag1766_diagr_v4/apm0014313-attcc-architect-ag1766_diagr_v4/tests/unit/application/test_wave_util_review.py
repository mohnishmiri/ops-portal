"""
Unit tests for WaveUtilReviewService (V04b).

Verifies:
- Accept operates on candidate IDs
- NEW_ROW acceptance creates canonical row
- EXACT_MATCH acceptance appends revision
- Reject requires reason and never changes canonical state
- Retire requires rationale and expected version
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake, Base
from migration_intake.persistence.models_evidence import EvidenceItem, WaveUtilRow
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.application.services.wave_util_review import (
    WaveUtilReviewService,
    WaveUtilCandidateAcceptItem,
    WaveUtilRetireItem,
    CandidateNotProposedError,
    InvalidMatchOutcomeError,
)
from migration_intake.application.errors import ConcurrencyConflictError
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
def service(session_factory) -> WaveUtilReviewService:
    """Create a WaveUtilReviewService instance."""
    return WaveUtilReviewService(session_factory)


@pytest.fixture
def actor_context() -> ActorContext:
    """Create an actor context for testing."""
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
    )


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

        # Evidence
        evidence_id = str(uuid.uuid4())
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

        # Import run
        run_id = str(uuid.uuid4())
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

        session.commit()

        return {
            "actor_id": actor_id,
            "app_id": app_id,
            "catalog_id": catalog_id,
            "intake_id": intake_id,
            "evidence_id": evidence_id,
            "run_id": run_id,
        }


def _create_new_row_candidate(session_factory, prereqs: dict) -> str:
    """Create a NEW_ROW candidate and return its ID."""
    with session_factory() as session:
        repo = CandidateRepository(session)
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="WAVEUTIL_ROW",
            target_key="WAVEUTIL-NEW-server-001",
            origin="wave_util_import",
            extractor_version="1.0.0",
            contract_version="WAVEUTIL_V1",
            raw_value_json={
                "server_name": "server-001",
                "environment": "PROD",
                "scope": "IN_SCOPE",
                "fields": {"cpu": "8", "memory": "32GB"},
                "match_outcome": "NEW_ROW",
                "matched_row_id": None,
            },
        )
        session.commit()
        return str(candidate.id)


def _create_exact_match_candidate(session_factory, prereqs: dict, matched_row_id: str) -> str:
    """Create an EXACT_MATCH candidate and return its ID."""
    with session_factory() as session:
        repo = CandidateRepository(session)
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="WAVEUTIL_ROW",
            target_key=f"WAVEUTIL-{matched_row_id}",
            origin="wave_util_import",
            extractor_version="1.0.0",
            contract_version="WAVEUTIL_V1",
            raw_value_json={
                "server_name": "server-001",
                "environment": "PROD",
                "scope": "IN_SCOPE",
                "fields": {"cpu": "16", "memory": "64GB"},
                "match_outcome": "EXACT_MATCH",
                "matched_row_id": matched_row_id,
            },
        )
        session.commit()
        return str(candidate.id)


def _create_wave_util_row(session_factory, prereqs: dict) -> str:
    """Create a WaveUtil row and return its ID."""
    now = datetime.now(tz=timezone.utc)
    row_id = str(uuid.uuid4())

    with session_factory() as session:
        repo = WaveUtilRepository(session)
        repo.add_row(
            row_id=row_id,
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            server_name="server-001",
            normalized_server_name="server-001",
            environment="PROD",
            scope="IN_SCOPE",
            created_at=now,
            created_by_id=prereqs["actor_id"],
        )
        rev_id = str(uuid.uuid4())
        repo.add_revision(
            revision_id=rev_id,
            row_id=row_id,
            revision_number=1,
            field_values_json={"cpu": "8", "memory": "32GB"},
            authored_at=now,
            authored_by_id=prereqs["actor_id"],
        )
        repo.advance_current_pointer(row_id, rev_id)
        session.commit()

    return row_id


class TestAcceptCandidates:
    """Tests for accept_candidates."""

    def test_accept_new_row_creates_canonical_row(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Accepting NEW_ROW candidate creates a canonical row."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_new_row_candidate(session_factory, prereqs)

        result = service.accept_candidates(
            items=[
                WaveUtilCandidateAcceptItem(
                    candidate_id=candidate_id,
                    expected_candidate_version=1,
                )
            ],
            actor=actor_context,
        )

        assert result["accepted"] == 1
        assert len(result["row_ids"]) == 1

        # Verify canonical row was created
        with session_factory() as session:
            repo = WaveUtilRepository(session)
            rows = repo.list_rows_for_application(prereqs["app_id"])
            assert len(rows) == 1
            assert rows[0]["server_name"] == "server-001"

    def test_accept_updates_candidate_state(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Accepting a candidate updates its state to ACCEPTED."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_new_row_candidate(session_factory, prereqs)

        service.accept_candidates(
            items=[
                WaveUtilCandidateAcceptItem(
                    candidate_id=candidate_id,
                    expected_candidate_version=1,
                )
            ],
            actor=actor_context,
        )

        with session_factory() as session:
            repo = CandidateRepository(session)
            candidate = repo.get_by_id(candidate_id)
            assert candidate.state == "ACCEPTED"

    def test_accept_exact_match_appends_revision(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Accepting EXACT_MATCH candidate appends revision to matched row."""
        prereqs = _seed_prerequisites(session_factory)
        row_id = _create_wave_util_row(session_factory, prereqs)
        candidate_id = _create_exact_match_candidate(session_factory, prereqs, row_id)

        result = service.accept_candidates(
            items=[
                WaveUtilCandidateAcceptItem(
                    candidate_id=candidate_id,
                    expected_candidate_version=1,
                )
            ],
            actor=actor_context,
        )

        assert result["accepted"] == 1
        assert row_id in result["row_ids"]

        # Verify revision was appended
        with session_factory() as session:
            repo = WaveUtilRepository(session)
            current_rev = repo.get_current_revision(row_id)
            assert current_rev["revision_number"] == 2

    def test_accept_version_mismatch_raises(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Accepting with wrong version raises ConcurrencyConflictError."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_new_row_candidate(session_factory, prereqs)

        with pytest.raises(ConcurrencyConflictError):
            service.accept_candidates(
                items=[
                    WaveUtilCandidateAcceptItem(
                        candidate_id=candidate_id,
                        expected_candidate_version=99,  # Wrong version
                    )
                ],
                actor=actor_context,
            )

    def test_accept_already_accepted_raises(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Accepting already-accepted candidate raises CandidateNotProposedError."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_new_row_candidate(session_factory, prereqs)

        # Accept once
        service.accept_candidates(
            items=[
                WaveUtilCandidateAcceptItem(
                    candidate_id=candidate_id,
                    expected_candidate_version=1,
                )
            ],
            actor=actor_context,
        )

        # Try to accept again
        with pytest.raises(CandidateNotProposedError):
            service.accept_candidates(
                items=[
                    WaveUtilCandidateAcceptItem(
                        candidate_id=candidate_id,
                        expected_candidate_version=2,
                    )
                ],
                actor=actor_context,
            )


class TestRejectCandidates:
    """Tests for reject_candidates."""

    def test_reject_updates_candidate_state(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Rejecting a candidate updates its state to REJECTED."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_new_row_candidate(session_factory, prereqs)

        result = service.reject_candidates(
            candidate_ids=[candidate_id],
            reason="Value is incorrect",
            actor=actor_context,
        )

        assert result["rejected"] == 1

        with session_factory() as session:
            repo = CandidateRepository(session)
            candidate = repo.get_by_id(candidate_id)
            assert candidate.state == "REJECTED"
            assert candidate.decision_rationale == "Value is incorrect"

    def test_reject_does_not_create_canonical_row(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Rejecting a candidate does not create a canonical row."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_new_row_candidate(session_factory, prereqs)

        service.reject_candidates(
            candidate_ids=[candidate_id],
            reason="Not applicable",
            actor=actor_context,
        )

        # Verify no canonical row was created
        with session_factory() as session:
            repo = WaveUtilRepository(session)
            rows = repo.list_rows_for_application(prereqs["app_id"])
            assert len(rows) == 0

    def test_reject_without_reason_raises(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Rejecting without reason raises ValueError."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_new_row_candidate(session_factory, prereqs)

        with pytest.raises(ValueError, match="requires a reason"):
            service.reject_candidates(
                candidate_ids=[candidate_id],
                reason="",
                actor=actor_context,
            )


class TestRetireRows:
    """Tests for retire_rows."""

    def test_retire_updates_row_state(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Retiring a row updates its state to RETIRED."""
        prereqs = _seed_prerequisites(session_factory)
        row_id = _create_wave_util_row(session_factory, prereqs)

        # Get current version
        with session_factory() as session:
            repo = WaveUtilRepository(session)
            row = repo.get_row(row_id)
            current_version = row["row_version"]

        result = service.retire_rows(
            items=[
                WaveUtilRetireItem(
                    row_id=row_id,
                    expected_row_version=current_version,
                    rationale="Server decommissioned",
                )
            ],
            actor=actor_context,
        )

        assert result["retired"] == 1

        with session_factory() as session:
            repo = WaveUtilRepository(session)
            row = repo.get_row(row_id)
            assert row["state"] == "RETIRED"

    def test_retire_without_rationale_raises(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Retiring without rationale raises ValueError."""
        prereqs = _seed_prerequisites(session_factory)
        row_id = _create_wave_util_row(session_factory, prereqs)

        with pytest.raises(ValueError, match="requires a rationale"):
            service.retire_rows(
                items=[
                    WaveUtilRetireItem(
                        row_id=row_id,
                        expected_row_version=1,
                        rationale="",
                    )
                ],
                actor=actor_context,
            )

    def test_retire_version_mismatch_raises(
        self, session_factory, service: WaveUtilReviewService, actor_context: ActorContext
    ) -> None:
        """Retiring with wrong version raises ConcurrencyConflictError."""
        prereqs = _seed_prerequisites(session_factory)
        row_id = _create_wave_util_row(session_factory, prereqs)

        with pytest.raises(ConcurrencyConflictError):
            service.retire_rows(
                items=[
                    WaveUtilRetireItem(
                        row_id=row_id,
                        expected_row_version=99,  # Wrong version
                        rationale="Server decommissioned",
                    )
                ],
                actor=actor_context,
            )
