"""
Contract tests for CandidateRepository (P06).

Verifies:
- Candidate CRUD operations
- Finding operations
- Evidence link operations
- State transitions
- Concurrency control
- Query filters
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Import all models to ensure they're registered with Base.metadata
from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    CatalogRelease,
    CatalogSection,
    CatalogQuestion,
    Intake,
    Base,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_candidates import (
    AnswerEvidenceLink,
    Candidate,
    CandidateFinding,
)
from migration_intake.persistence.repositories.candidates import CandidateRepository


@pytest.fixture
def tmp_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(tmp_engine):
    """Create a session for testing."""
    Session_ = sessionmaker(bind=tmp_engine)
    session = Session_()
    yield session
    session.close()


@pytest.fixture
def repo(session) -> CandidateRepository:
    """Create a repository instance."""
    return CandidateRepository(session)


def _seed_prerequisites(session) -> dict:
    """
    Seed prerequisite records for candidate tests.
    
    Returns dict with actor_id, app_id, catalog_id, intake_id, evidence_id, run_id.
    """
    now = datetime.now(tz=timezone.utc)
    
    # Actor
    actor_id = str(uuid.uuid4())
    session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))
    
    # Application
    app_id = str(uuid.uuid4())
    session.add(Application(
        id=app_id,
        state="ACTIVE",
        display_name="Test App",
        created_at=now,
        updated_at=now,
        row_version=1,
        created_by_id=actor_id,
    ))
    
    # Catalog
    catalog_id = str(uuid.uuid4())
    session.add(CatalogRelease(
        id=catalog_id,
        semantic_version="1.0.0",
        source_filename="catalog.yaml",
        source_sha256="a" * 64,
        compiler_version="1.0",
        pub_state="PUBLISHED",
        published_at=now,
        created_at=now,
    ))
    
    # Intake
    intake_id = str(uuid.uuid4())
    session.add(Intake(
        id=intake_id,
        application_id=app_id,
        catalog_id=catalog_id,
        state="DRAFT",
        created_at=now,
        updated_at=now,
        row_version=1,
        created_by_id=actor_id,
    ))
    
    # Evidence
    evidence_id = str(uuid.uuid4())
    session.add(EvidenceItem(
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
    ))
    
    # Import run
    run_id = str(uuid.uuid4())
    session.add(ImportRun(
        id=run_id,
        application_id=app_id,
        intake_id=intake_id,
        evidence_item_id=evidence_id,
        contract_name="test_contract",
        parser_version="1.0.0",
        state="COMPLETED",
        total_candidates=0,
        total_findings=0,
        created_at=now,
        completed_at=now,
        created_by_id=actor_id,
    ))
    
    session.commit()
    
    return {
        "actor_id": actor_id,
        "app_id": app_id,
        "catalog_id": catalog_id,
        "intake_id": intake_id,
        "evidence_id": evidence_id,
        "run_id": run_id,
    }


class TestCandidateCreate:
    """Tests for candidate creation."""

    def test_create_candidate_with_required_fields(
        self, session, repo: CandidateRepository
    ) -> None:
        """Can create a candidate with required fields."""
        prereqs = _seed_prerequisites(session)
        
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="app_sheet_adapter",
            extractor_version="1.0.0",
            contract_version="1.0",
            raw_value_json={"text": "Test value"},
        )
        session.commit()
        
        assert candidate.id is not None
        assert candidate.state == "PROPOSED"
        assert candidate.row_version == 1
        assert candidate.raw_value_json == {"text": "Test value"}

    def test_create_candidate_with_all_fields(
        self, session, repo: CandidateRepository
    ) -> None:
        """Can create a candidate with all optional fields."""
        prereqs = _seed_prerequisites(session)
        
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="app_sheet_adapter",
            extractor_version="1.0.0",
            contract_version="1.0",
            raw_value_json={"text": "Test value"},
            normalized_value_json={"text": "Normalized value"},
            scope_json={"environment": "PROD"},
            source_locator={"sheet": "App", "row": 5, "column": "B"},
            confidence=0.95,
            response_schema_version="1.0",
        )
        session.commit()
        
        assert candidate.normalized_value_json == {"text": "Normalized value"}
        assert candidate.scope_json == {"environment": "PROD"}
        assert candidate.source_locator == {"sheet": "App", "row": 5, "column": "B"}
        assert candidate.confidence == 0.95


class TestCandidateQuery:
    """Tests for candidate queries."""

    def test_get_by_id(self, session, repo: CandidateRepository) -> None:
        """Can retrieve a candidate by ID."""
        prereqs = _seed_prerequisites(session)
        
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "Test"},
        )
        session.commit()
        
        retrieved = repo.get_by_id(candidate.id)
        assert retrieved is not None
        assert retrieved.id == candidate.id

    def test_get_by_id_not_found(self, session, repo: CandidateRepository) -> None:
        """Returns None for unknown ID."""
        result = repo.get_by_id(str(uuid.uuid4()))
        assert result is None

    def test_get_by_intake(self, session, repo: CandidateRepository) -> None:
        """Can retrieve candidates by intake."""
        prereqs = _seed_prerequisites(session)
        
        # Create 3 candidates
        for i in range(3):
            repo.create_candidate(
                import_run_id=prereqs["run_id"],
                application_id=prereqs["app_id"],
                intake_id=prereqs["intake_id"],
                evidence_item_id=prereqs["evidence_id"],
                target_kind="QUESTION",
                target_key=f"Q-{i:03d}",
                origin="test",
                extractor_version="1.0",
                contract_version="1.0",
                raw_value_json={"index": i},
            )
        session.commit()
        
        candidates = repo.get_by_intake(prereqs["intake_id"])
        assert len(candidates) == 3

    def test_get_by_intake_with_state_filter(
        self, session, repo: CandidateRepository
    ) -> None:
        """Can filter candidates by state."""
        prereqs = _seed_prerequisites(session)
        
        # Create candidates with different states
        c1 = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "1"},
        )
        c2 = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-002",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "2"},
        )
        session.commit()
        
        # Update one to ACCEPTED
        repo.update_state(c1.id, "ACCEPTED", prereqs["actor_id"])
        session.commit()
        
        proposed = repo.get_by_intake(prereqs["intake_id"], state="PROPOSED")
        assert len(proposed) == 1
        assert proposed[0].id == c2.id

    def test_get_by_target(self, session, repo: CandidateRepository) -> None:
        """Can retrieve candidates by target."""
        prereqs = _seed_prerequisites(session)
        
        # Create candidates for different targets
        repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "1"},
        )
        repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-002",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "2"},
        )
        session.commit()
        
        candidates = repo.get_by_target(
            prereqs["intake_id"], "QUESTION", "Q-001"
        )
        assert len(candidates) == 1
        assert candidates[0].target_key == "Q-001"

    def test_count_by_intake(self, session, repo: CandidateRepository) -> None:
        """Can count candidates by intake."""
        prereqs = _seed_prerequisites(session)
        
        for i in range(5):
            repo.create_candidate(
                import_run_id=prereqs["run_id"],
                application_id=prereqs["app_id"],
                intake_id=prereqs["intake_id"],
                evidence_item_id=prereqs["evidence_id"],
                target_kind="QUESTION",
                target_key=f"Q-{i:03d}",
                origin="test",
                extractor_version="1.0",
                contract_version="1.0",
                raw_value_json={"index": i},
            )
        session.commit()
        
        count = repo.count_by_intake(prereqs["intake_id"])
        assert count == 5


class TestCandidateStateTransition:
    """Tests for candidate state transitions."""

    def test_update_state_to_accepted(
        self, session, repo: CandidateRepository
    ) -> None:
        """Can transition candidate to ACCEPTED."""
        prereqs = _seed_prerequisites(session)
        
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "Test"},
        )
        session.commit()
        
        updated = repo.update_state(
            candidate.id,
            "ACCEPTED",
            prereqs["actor_id"],
            decision_rationale="Looks correct",
        )
        session.commit()
        
        assert updated.state == "ACCEPTED"
        assert str(updated.decided_by_id) == prereqs["actor_id"]
        assert updated.decision_rationale == "Looks correct"
        assert updated.decided_at is not None
        assert updated.row_version == 2

    def test_update_state_with_edit(
        self, session, repo: CandidateRepository
    ) -> None:
        """Can accept with edited value."""
        prereqs = _seed_prerequisites(session)
        
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "Original"},
        )
        session.commit()
        
        updated = repo.update_state(
            candidate.id,
            "ACCEPTED_WITH_EDIT",
            prereqs["actor_id"],
            accepted_value_json={"text": "Edited"},
        )
        session.commit()
        
        assert updated.state == "ACCEPTED_WITH_EDIT"
        assert updated.raw_value_json == {"text": "Original"}  # preserved
        assert updated.accepted_value_json == {"text": "Edited"}

    def test_update_state_version_mismatch(
        self, session, repo: CandidateRepository
    ) -> None:
        """Raises error on version mismatch."""
        prereqs = _seed_prerequisites(session)
        
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "Test"},
        )
        session.commit()
        
        with pytest.raises(ValueError, match="Version mismatch"):
            repo.update_state(
                candidate.id,
                "ACCEPTED",
                prereqs["actor_id"],
                expected_version=99,
            )


class TestCandidateFinding:
    """Tests for candidate findings."""

    def test_create_finding(self, session, repo: CandidateRepository) -> None:
        """Can create a finding."""
        prereqs = _seed_prerequisites(session)
        
        finding = repo.create_finding(
            import_run_id=prereqs["run_id"],
            finding_type="VALIDATION_WARNING",
            severity="WARNING",
            message="Value may be outdated",
        )
        session.commit()
        
        assert finding.id is not None
        assert finding.finding_type == "VALIDATION_WARNING"
        assert finding.severity == "WARNING"

    def test_create_finding_with_candidate(
        self, session, repo: CandidateRepository
    ) -> None:
        """Can create a finding linked to a candidate."""
        prereqs = _seed_prerequisites(session)
        
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key="Q-001",
            origin="test",
            extractor_version="1.0",
            contract_version="1.0",
            raw_value_json={"text": "Test"},
        )
        session.commit()
        
        finding = repo.create_finding(
            import_run_id=prereqs["run_id"],
            finding_type="CONFLICT",
            severity="ERROR",
            message="Conflicts with existing value",
            candidate_id=candidate.id,
        )
        session.commit()
        
        findings = repo.get_findings_by_candidate(candidate.id)
        assert len(findings) == 1
        assert findings[0].id == finding.id

    def test_get_findings_by_run(self, session, repo: CandidateRepository) -> None:
        """Can retrieve findings by run."""
        prereqs = _seed_prerequisites(session)
        
        for i in range(3):
            repo.create_finding(
                import_run_id=prereqs["run_id"],
                finding_type="INFO",
                severity="INFO",
                message=f"Finding {i}",
            )
        session.commit()
        
        findings = repo.get_findings_by_run(prereqs["run_id"])
        assert len(findings) == 3


class TestAnswerEvidenceLink:
    """Tests for answer-evidence links."""

    def test_create_evidence_link(self, session, repo: CandidateRepository) -> None:
        """Can create an evidence link."""
        prereqs = _seed_prerequisites(session)
        
        # Need an answer revision - create minimal one
        # Models already imported at module level
        
        now = datetime.now(tz=timezone.utc)
        
        # Section
        section_id = str(uuid.uuid4())
        session.add(CatalogSection(
            id=section_id,
            release_id=prereqs["catalog_id"],
            section_code="SEC-001",
            display_name="Section 1",
            display_order=1,
        ))
        
        # Question
        question_id = str(uuid.uuid4())
        session.add(CatalogQuestion(
            id=question_id,
            section_id=section_id,
            question_code="Q-001",
            question_text="Test question",
            response_type="TEXT",
            required_level="OPTIONAL",
            collection_mode="SINGLE",
            display_order=1,
        ))
        
        # Answer instance
        instance_id = str(uuid.uuid4())
        session.add(AnswerInstance(
            id=instance_id,
            intake_id=prereqs["intake_id"],
            question_id=question_id,
            created_at=now,
            updated_at=now,
            row_version=1,
        ))
        
        # Answer revision
        revision_id = str(uuid.uuid4())
        session.add(AnswerRevision(
            id=revision_id,
            instance_id=instance_id,
            revision_number=1,
            response_json={"text": "Test"},
            confirm_state="DRAFT",
            authored_at=now,
            authored_by_id=prereqs["actor_id"],
        ))
        session.commit()
        
        # Create link
        link = repo.create_evidence_link(
            revision_id=revision_id,
            evidence_item_id=prereqs["evidence_id"],
            link_type="IMPORT_ACCEPTANCE",
        )
        session.commit()
        
        assert link.id is not None
        assert link.link_type == "IMPORT_ACCEPTANCE"
        
        # Retrieve
        links = repo.get_evidence_links_by_revision(revision_id)
        assert len(links) == 1
        assert links[0].id == link.id
