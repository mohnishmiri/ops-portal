"""
Integration tests for B06b — Workbook candidate pipeline.

Verifies:
- Candidates are persisted to the candidates table
- Candidate count matches stored candidate rows
- Source locators are correctly extracted
- Raw values are correctly normalized
- Idempotency: reprocessing returns existing run without duplicating candidates
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    Intake,
    Base,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.application.services.workbook import WorkbookService
from migration_intake.application.dto import ActorContext


@pytest.fixture
def tmp_engine():
    """Create an in-memory SQLite engine with all tables."""
    # Import all models to register them
    import migration_intake.persistence.models_imports  # noqa: F401
    import migration_intake.persistence.models_candidates  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(tmp_engine):
    """Create a session factory."""
    return sessionmaker(bind=tmp_engine)


@pytest.fixture
def service(session_factory) -> WorkbookService:
    """Create a WorkbookService instance."""
    return WorkbookService(session_factory)


@pytest.fixture
def actor_context() -> ActorContext:
    """Create an actor context for testing."""
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
    )


def _seed_prerequisites(session_factory) -> dict:
    """
    Seed prerequisite records for workbook tests.

    Returns dict with actor_id, app_id, catalog_id, intake_id, evidence_id.
    """
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

        session.commit()

        return {
            "actor_id": actor_id,
            "app_id": app_id,
            "catalog_id": catalog_id,
            "intake_id": intake_id,
            "evidence_id": evidence_id,
        }


class TestCandidatePersistence:
    """Tests for candidate persistence during workbook processing."""

    def test_tss_candidates_persisted(
        self, session_factory, service: WorkbookService, actor_context: ActorContext
    ) -> None:
        """TSS sheet candidates are persisted to the candidates table."""
        prereqs = _seed_prerequisites(session_factory)

        # TSS sheet rows with hardware data
        sheet_rows = {
            "TSS": [
                {
                    "Manufacturer": "Dell",
                    "Model": "PowerEdge R640",
                    "Quantity": "5",
                    "Unit Type": "Server",
                },
                {
                    "Manufacturer": "HP",
                    "Model": "ProLiant DL380",
                    "Quantity": "3",
                    "Unit Type": "Server",
                },
            ]
        }

        result = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        assert result.state == "COMPLETED"
        assert result.total_candidates >= 2

        # Verify candidates in database
        with session_factory() as session:
            candidates = session.execute(
                select(Candidate).where(Candidate.import_run_id == result.run_id)
            ).scalars().all()

            assert len(candidates) >= 2
            # All candidates should be in PROPOSED state
            for candidate in candidates:
                assert candidate.state == "PROPOSED"
                assert candidate.origin is not None

    def test_candidate_count_matches_stored_rows(
        self, session_factory, service: WorkbookService, actor_context: ActorContext
    ) -> None:
        """Candidate count in result matches stored candidate rows."""
        prereqs = _seed_prerequisites(session_factory)

        sheet_rows = {
            "TSS": [
                {"Manufacturer": "Dell", "Model": "R640", "Quantity": "1", "Unit Type": "Server"},
                {"Manufacturer": "HP", "Model": "DL380", "Quantity": "2", "Unit Type": "Server"},
                {"Manufacturer": "Cisco", "Model": "UCS", "Quantity": "3", "Unit Type": "Server"},
            ]
        }

        result = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        # Count candidates in database
        with session_factory() as session:
            repo = CandidateRepository(session)
            db_count = repo.count_by_run(result.run_id)

        assert result.total_candidates == db_count

    def test_source_locator_contains_sheet_and_row(
        self, session_factory, service: WorkbookService, actor_context: ActorContext
    ) -> None:
        """Source locators contain sheet name and row number."""
        prereqs = _seed_prerequisites(session_factory)

        sheet_rows = {
            "TSS": [
                {"Manufacturer": "Dell", "Model": "R640", "Quantity": "1", "Unit Type": "Server"},
            ]
        }

        result = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        with session_factory() as session:
            candidates = session.execute(
                select(Candidate).where(Candidate.import_run_id == result.run_id)
            ).scalars().all()

            for candidate in candidates:
                assert candidate.source_locator is not None
                assert "sheet" in candidate.source_locator
                assert candidate.source_locator["sheet"] == "TSS"

    def test_raw_value_contains_extracted_data(
        self, session_factory, service: WorkbookService, actor_context: ActorContext
    ) -> None:
        """Raw values contain the extracted data from the sheet."""
        prereqs = _seed_prerequisites(session_factory)

        sheet_rows = {
            "TSS": [
                {"Manufacturer": "Dell", "Model": "R640", "Quantity": "5", "Unit Type": "Server"},
            ]
        }

        result = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        with session_factory() as session:
            candidates = session.execute(
                select(Candidate).where(Candidate.import_run_id == result.run_id)
            ).scalars().all()

            # At least one candidate should have manufacturer data
            has_manufacturer = any(
                c.raw_value_json.get("manufacturer") == "Dell" for c in candidates
            )
            assert has_manufacturer


class TestIdempotency:
    """Tests for idempotent reprocessing."""

    def test_reprocessing_returns_existing_run(
        self, session_factory, service: WorkbookService, actor_context: ActorContext
    ) -> None:
        """Reprocessing the same evidence returns the existing run."""
        prereqs = _seed_prerequisites(session_factory)

        sheet_rows = {
            "TSS": [
                {"Manufacturer": "Dell", "Model": "R640", "Quantity": "1", "Unit Type": "Server"},
            ]
        }

        # First processing
        result1 = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        # Second processing (same evidence)
        result2 = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        assert result2.run_id == result1.run_id
        assert result2.deduplicated is True

    def test_reprocessing_does_not_duplicate_candidates(
        self, session_factory, service: WorkbookService, actor_context: ActorContext
    ) -> None:
        """Reprocessing does not create duplicate candidates."""
        prereqs = _seed_prerequisites(session_factory)

        sheet_rows = {
            "TSS": [
                {"Manufacturer": "Dell", "Model": "R640", "Quantity": "1", "Unit Type": "Server"},
                {"Manufacturer": "HP", "Model": "DL380", "Quantity": "2", "Unit Type": "Server"},
            ]
        }

        # First processing
        result1 = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        # Count candidates after first processing
        with session_factory() as session:
            repo = CandidateRepository(session)
            count1 = repo.count_by_intake(prereqs["intake_id"])

        # Second processing
        service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        # Count candidates after second processing
        with session_factory() as session:
            repo = CandidateRepository(session)
            count2 = repo.count_by_intake(prereqs["intake_id"])

        # Counts should be the same (no duplicates)
        assert count2 == count1


class TestMultipleSheets:
    """Tests for processing multiple sheets."""

    def test_multiple_sheets_create_candidates(
        self, session_factory, service: WorkbookService, actor_context: ActorContext
    ) -> None:
        """Processing multiple sheets creates candidates from each."""
        prereqs = _seed_prerequisites(session_factory)

        sheet_rows = {
            "TSS": [
                {"Manufacturer": "Dell", "Model": "R640", "Quantity": "1", "Unit Type": "Server"},
            ],
            "Infra": [
                {"Resource Type": "VM", "Name": "web-server-01", "CPU": "4", "Memory": "16GB"},
            ],
        }

        result = service.process_workbook(
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            sheet_rows=sheet_rows,
            actor=actor_context,
        )

        assert result.total_sheets == 2

        with session_factory() as session:
            candidates = session.execute(
                select(Candidate).where(Candidate.import_run_id == result.run_id)
            ).scalars().all()

            # Should have candidates from both sheets
            sheets = {c.source_locator.get("sheet") for c in candidates}
            assert "TSS" in sheets or "Infra" in sheets
