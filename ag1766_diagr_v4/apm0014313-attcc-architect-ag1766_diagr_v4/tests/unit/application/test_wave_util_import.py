"""
Unit tests for WaveUtilImportService (V04b).

Verifies:
- All valid outcomes create candidates (not direct canonical rows)
- Invalid outcomes create findings
- Candidate records contain match outcome and matched row ID
- Confidence scores are set based on outcome
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake, Base
from migration_intake.persistence.models_evidence import EvidenceItem, WaveUtilRow
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.application.services.wave_util_import import (
    WaveUtilImportService,
    WaveUtilImportResult,
)
from migration_intake.domain.wave_util_matching import SourceRow
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
def service(session_factory) -> WaveUtilImportService:
    """Create a WaveUtilImportService instance."""
    return WaveUtilImportService(session_factory)


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
                state="PENDING",
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


class TestCandidateCreation:
    """Tests for candidate creation (V04b invariant)."""

    def test_new_row_creates_candidate(
        self, session_factory, service: WaveUtilImportService, actor_context: ActorContext
    ) -> None:
        """NEW_ROW outcome creates a candidate, not a direct canonical row."""
        prereqs = _seed_prerequisites(session_factory)

        source_rows = [
            SourceRow(
                server_name="server-001",
                environment="PROD",
                scope="IN_SCOPE",
                raw_fields={"cpu": "8", "memory": "32GB"},
                source_locator="Sheet:WaveUtil/Row:2",
            ),
        ]

        result = service.import_batch(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            import_run_id=prereqs["run_id"],
            source_rows=source_rows,
            actor=actor_context,
        )

        assert result.candidates_created == 1
        assert result.skipped_rows == 0
        assert len(result.row_results) == 1
        assert result.row_results[0].candidate_id is not None
        assert result.row_results[0].outcome == "NEW_ROW"

        # Verify candidate in database
        with session_factory() as session:
            repo = CandidateRepository(session)
            candidate = repo.get_by_id(result.row_results[0].candidate_id)
            assert candidate is not None
            assert candidate.state == "PROPOSED"
            assert candidate.target_kind == "WAVEUTIL_ROW"

    def test_candidate_contains_match_outcome(
        self, session_factory, service: WaveUtilImportService, actor_context: ActorContext
    ) -> None:
        """Candidate raw_value_json contains match outcome."""
        prereqs = _seed_prerequisites(session_factory)

        source_rows = [
            SourceRow(
                server_name="server-002",
                environment="DEV",
                scope="IN_SCOPE",
                raw_fields={"cpu": "4"},
                source_locator="Sheet:WaveUtil/Row:3",
            ),
        ]

        result = service.import_batch(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            import_run_id=prereqs["run_id"],
            source_rows=source_rows,
            actor=actor_context,
        )

        with session_factory() as session:
            repo = CandidateRepository(session)
            candidate = repo.get_by_id(result.row_results[0].candidate_id)
            assert candidate.raw_value_json["match_outcome"] == "NEW_ROW"
            assert candidate.raw_value_json["server_name"] == "server-002"

    def test_confidence_set_for_new_row(
        self, session_factory, service: WaveUtilImportService, actor_context: ActorContext
    ) -> None:
        """NEW_ROW candidates have confidence score of 0.9."""
        prereqs = _seed_prerequisites(session_factory)

        source_rows = [
            SourceRow(
                server_name="server-003",
                environment="PROD",
                scope="IN_SCOPE",
                raw_fields={},
                source_locator="Sheet:WaveUtil/Row:4",
            ),
        ]

        result = service.import_batch(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            import_run_id=prereqs["run_id"],
            source_rows=source_rows,
            actor=actor_context,
        )

        with session_factory() as session:
            repo = CandidateRepository(session)
            candidate = repo.get_by_id(result.row_results[0].candidate_id)
            assert candidate.confidence == 0.9


class TestInvalidOutcomes:
    """Tests for invalid outcomes (skipped rows)."""

    def test_invalid_identity_skipped(
        self, session_factory, service: WaveUtilImportService, actor_context: ActorContext
    ) -> None:
        """INVALID_IDENTITY outcome is skipped (no candidate created)."""
        prereqs = _seed_prerequisites(session_factory)

        source_rows = [
            SourceRow(
                server_name="",  # Empty server name → INVALID_IDENTITY
                environment="PROD",
                scope="IN_SCOPE",
                raw_fields={},
                source_locator="Sheet:WaveUtil/Row:5",
            ),
        ]

        result = service.import_batch(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            import_run_id=prereqs["run_id"],
            source_rows=source_rows,
            actor=actor_context,
        )

        assert result.candidates_created == 0
        assert result.skipped_rows == 1
        assert result.row_results[0].outcome == "INVALID_IDENTITY"
        assert result.row_results[0].candidate_id is None


class TestBatchProcessing:
    """Tests for batch processing."""

    def test_multiple_rows_create_multiple_candidates(
        self, session_factory, service: WaveUtilImportService, actor_context: ActorContext
    ) -> None:
        """Multiple valid rows create multiple candidates."""
        prereqs = _seed_prerequisites(session_factory)

        source_rows = [
            SourceRow(
                server_name="server-a",
                environment="PROD",
                scope="IN_SCOPE",
                raw_fields={},
                source_locator="Sheet:WaveUtil/Row:2",
            ),
            SourceRow(
                server_name="server-b",
                environment="DEV",
                scope="IN_SCOPE",
                raw_fields={},
                source_locator="Sheet:WaveUtil/Row:3",
            ),
            SourceRow(
                server_name="server-c",
                environment="UAT",
                scope="IN_SCOPE",
                raw_fields={},
                source_locator="Sheet:WaveUtil/Row:4",
            ),
        ]

        result = service.import_batch(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            import_run_id=prereqs["run_id"],
            source_rows=source_rows,
            actor=actor_context,
        )

        assert result.total_rows == 3
        assert result.candidates_created == 3
        assert all(r.candidate_id is not None for r in result.row_results)
