"""
Unit tests for CandidateService (A04).

Verifies:
- Accept candidate transitions state to ACCEPTED
- Accept with edit preserves original value
- Reject requires reason
- Defer requires reason
- Concurrency control with expected_version
- State validation (only PROPOSED can be acted on)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import threading

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

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
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_candidates import AnswerEvidenceLink, Candidate
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.application.services.candidates import (
    CandidateService,
    CandidateNotFoundError,
    CandidateNotProposedError,
    CandidateTargetNotInCatalogError,
    NonQuestionCandidateError,
    RejectReasonRequiredError,
    DeferReasonRequiredError,
)
from migration_intake.application.services.answers import AnswerService
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
def service(session_factory) -> CandidateService:
    """Create a CandidateService instance."""
    return CandidateService(session_factory)


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

        # Intake (DRAFT state - open for editing)
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

        # Seed a default question so QUESTION-target candidates can be validated.
        section_id = str(uuid.uuid4())
        session.add(
            CatalogSection(
                id=section_id,
                release_id=catalog_id,
                section_code="APPLICATION",
                display_name="Application",
                display_order=1,
            )
        )
        session.flush()
        session.add(
            CatalogQuestion(
                id=str(uuid.uuid4()),
                section_id=section_id,
                question_code="Q-001",
                question_text="Free text question",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="AUTO_IMPORT",
                display_order=1,
                is_active=True,
                response_schema_version="1.0",
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
                contract_name="test_contract",
                parser_version="1.0.0",
                state="COMPLETED",
                total_candidates=0,
                total_findings=0,
                created_at=now,
                completed_at=now,
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


def _create_candidate(
    session_factory,
    prereqs: dict,
    *,
    target_key: str = "Q-001",
) -> str:
    """Create a candidate and return its ID."""
    with session_factory() as session:
        repo = CandidateRepository(session)
        candidate = repo.create_candidate(
            import_run_id=prereqs["run_id"],
            application_id=prereqs["app_id"],
            intake_id=prereqs["intake_id"],
            evidence_item_id=prereqs["evidence_id"],
            target_kind="QUESTION",
            target_key=target_key,
            origin="test_adapter",
            extractor_version="1.0.0",
            contract_version="1.0",
            raw_value_json={"text": "Test value"},
        )
        session.commit()
        return candidate.id


class TestAcceptCandidate:
    """Tests for accept_candidate."""

    def test_accept_transitions_to_accepted(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Accepting a candidate transitions it to ACCEPTED state."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        result = service.accept_candidate(candidate_id, actor_context)

        assert result["state"] == "ACCEPTED"
        assert result["candidate_id"] == candidate_id

        # Verify in database
        candidate = service.get_candidate(candidate_id)
        assert candidate["state"] == "ACCEPTED"
        assert candidate["decided_by_id"] is not None

    def test_accept_with_rationale(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Acceptance rationale is recorded."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        service.accept_candidate(
            candidate_id, actor_context, rationale="Value looks correct"
        )

        candidate = service.get_candidate(candidate_id)
        assert candidate["decision_rationale"] == "Value looks correct"

    def test_accept_not_found_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Accepting unknown candidate raises CandidateNotFoundError."""
        _seed_prerequisites(session_factory)

        with pytest.raises(CandidateNotFoundError):
            service.accept_candidate(str(uuid.uuid4()), actor_context)

    def test_accept_already_accepted_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Accepting already-accepted candidate raises CandidateNotProposedError."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        # Accept once
        service.accept_candidate(candidate_id, actor_context)

        # Try to accept again
        with pytest.raises(CandidateNotProposedError):
            service.accept_candidate(candidate_id, actor_context)

    def test_accept_version_mismatch_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Accepting with wrong version raises ConcurrencyConflictError."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        with pytest.raises(ConcurrencyConflictError):
            service.accept_candidate(
                candidate_id, actor_context, expected_version=99
            )

    def test_concurrent_accept_produces_one_winner_one_conflict(
        self,
        tmp_path,
        actor_context: ActorContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Concurrent acceptance yields one ACCEPTED and one concurrency conflict."""
        engine = create_engine(
            f"sqlite:///{tmp_path / 'candidate-concurrency.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        threaded_session_factory = sessionmaker(bind=engine)
        prereqs = _seed_prerequisites(threaded_session_factory)
        candidate_id = _create_candidate(threaded_session_factory, prereqs)

        barrier = threading.Barrier(2, timeout=5)
        original_resolver = CandidateService._resolve_question_target

        def synchronized_resolver(self, *, session, candidate):  # type: ignore[no-untyped-def]
            barrier.wait()
            return original_resolver(self, session=session, candidate=candidate)

        monkeypatch.setattr(
            CandidateService,
            "_resolve_question_target",
            synchronized_resolver,
        )

        results: list[str] = []
        errors: list[type[Exception]] = []
        result_lock = threading.Lock()

        def _worker() -> None:
            worker_service = CandidateService(threaded_session_factory)
            try:
                result = worker_service.accept_candidate(candidate_id, actor_context)
                with result_lock:
                    results.append(result["state"])
            except Exception as exc:  # pragma: no cover - asserted below
                with result_lock:
                    errors.append(type(exc))

        first = threading.Thread(target=_worker)
        second = threading.Thread(target=_worker)
        first.start()
        second.start()
        first.join()
        second.join()

        assert results.count("ACCEPTED") == 1
        assert errors.count(ConcurrencyConflictError) == 1
        engine.dispose()


class TestNonQuestionCandidates:
    """Tests for non-QUESTION candidate rejection."""

    def test_accept_interface_register_candidate_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Interface register candidates cannot be accepted as questionnaire answers."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(
            session_factory,
            prereqs,
            target_key="INTERFACE-001",
        )

        with session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            candidate.target_kind = "INTERFACE_REGISTER"
            session.commit()

        with pytest.raises(NonQuestionCandidateError) as exc_info:
            service.accept_candidate(candidate_id, actor_context)

        assert "target_kind='INTERFACE_REGISTER'" in str(exc_info.value)
        assert "only QUESTION candidates" in str(exc_info.value)
        assert service.get_candidate(candidate_id)["state"] == "PROPOSED"

    def test_accept_waveutil_row_candidate_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Wave-util row candidates cannot be accepted as questionnaire answers."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(
            session_factory,
            prereqs,
            target_key="WAVEUTIL-001",
        )

        with session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            candidate.target_kind = "WAVEUTIL_ROW"
            session.commit()

        with pytest.raises(NonQuestionCandidateError):
            service.accept_candidate(candidate_id, actor_context)

        assert service.get_candidate(candidate_id)["state"] == "PROPOSED"

    def test_accept_with_edit_non_question_candidate_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Accept-with-edit also rejects non-QUESTION candidates."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(
            session_factory,
            prereqs,
            target_key="PROV-DC-CODE",
        )

        with session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            candidate.target_kind = "PROVISIONING_REFERENCE"
            session.commit()

        with pytest.raises(NonQuestionCandidateError):
            service.accept_with_edit(
                candidate_id,
                {"edited": "value"},
                actor_context,
            )

        assert service.get_candidate(candidate_id)["state"] == "PROPOSED"


class TestAcceptWithEdit:
    """Tests for accept_with_edit."""

    def test_accept_with_edit_preserves_original(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Accept with edit preserves original raw value."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        edited_value = {"text": "Edited value"}
        result = service.accept_with_edit(
            candidate_id, edited_value, actor_context
        )

        assert result["state"] == "ACCEPTED_WITH_EDIT"

        candidate = service.get_candidate(candidate_id)
        assert candidate["raw_value_json"] == {"text": "Test value"}  # original
        assert candidate["accepted_value_json"] == {"text": "Edited value"}  # edited


class TestRejectCandidate:
    """Tests for reject_candidate."""

    def test_reject_transitions_to_rejected(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Rejecting a candidate transitions it to REJECTED state."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        result = service.reject_candidate(
            candidate_id, "Value is incorrect", actor_context
        )

        assert result["state"] == "REJECTED"

        candidate = service.get_candidate(candidate_id)
        assert candidate["state"] == "REJECTED"
        assert candidate["decision_rationale"] == "Value is incorrect"

    def test_reject_without_reason_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Rejecting without reason raises RejectReasonRequiredError."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        with pytest.raises(RejectReasonRequiredError):
            service.reject_candidate(candidate_id, "", actor_context)

    def test_reject_with_whitespace_reason_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Rejecting with whitespace-only reason raises error."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        with pytest.raises(RejectReasonRequiredError):
            service.reject_candidate(candidate_id, "   ", actor_context)


class TestDeferCandidate:
    """Tests for defer_candidate."""

    def test_defer_transitions_to_deferred(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Deferring a candidate transitions it to DEFERRED state."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        result = service.defer_candidate(
            candidate_id, "Need more information", actor_context
        )

        assert result["state"] == "DEFERRED"

        candidate = service.get_candidate(candidate_id)
        assert candidate["state"] == "DEFERRED"

    def test_defer_without_reason_raises(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Deferring without reason raises DeferReasonRequiredError."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        with pytest.raises(DeferReasonRequiredError):
            service.defer_candidate(candidate_id, "", actor_context)

    def test_defer_with_assignment(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Deferring with assignment records assignee."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        assignee_id = str(uuid.uuid4())
        result = service.defer_candidate(
            candidate_id,
            "Need SME review",
            actor_context,
            assigned_to=assignee_id,
        )

        assert result["assigned_to"] == assignee_id

        candidate = service.get_candidate(candidate_id)
        assert assignee_id in candidate["decision_rationale"]


class TestQueryMethods:
    """Tests for query methods."""

    def test_get_candidate(
        self, session_factory, service: CandidateService
    ) -> None:
        """Can retrieve a candidate by ID."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)

        candidate = service.get_candidate(str(candidate_id))

        assert candidate is not None
        assert candidate["id"] == str(candidate_id)
        assert candidate["state"] == "PROPOSED"

    def test_get_candidate_not_found(
        self, session_factory, service: CandidateService
    ) -> None:
        """Returns None for unknown candidate."""
        _seed_prerequisites(session_factory)

        candidate = service.get_candidate(str(uuid.uuid4()))

        assert candidate is None

    def test_list_candidates_for_intake(
        self, session_factory, service: CandidateService
    ) -> None:
        """Can list candidates for an intake."""
        prereqs = _seed_prerequisites(session_factory)

        # Create multiple candidates
        for _ in range(3):
            _create_candidate(session_factory, prereqs)

        candidates = service.list_candidates_for_intake(prereqs["intake_id"])

        assert len(candidates) == 3

    def test_list_candidates_with_state_filter(
        self, session_factory, service: CandidateService, actor_context: ActorContext
    ) -> None:
        """Can filter candidates by state."""
        prereqs = _seed_prerequisites(session_factory)

        # Create candidates
        c1 = _create_candidate(session_factory, prereqs)
        c2 = _create_candidate(session_factory, prereqs)

        # Accept one
        service.accept_candidate(c1, actor_context)

        # Filter by PROPOSED
        proposed = service.list_candidates_for_intake(
            prereqs["intake_id"], state="PROPOSED"
        )

        assert len(proposed) == 1
        assert proposed[0]["id"] == str(c2)

    def test_count_candidates_for_intake(
        self, session_factory, service: CandidateService
    ) -> None:
        """Can count candidates for an intake."""
        prereqs = _seed_prerequisites(session_factory)

        for _ in range(5):
            _create_candidate(session_factory, prereqs)

        count = service.count_candidates_for_intake(prereqs["intake_id"])

        assert count == 5


class TestAcceptWithAnswerService:
    """
    Acceptance behaviour when an AnswerService is actually wired.

    Every other test in this file constructs ``CandidateService`` without an
    answer service, so the answer-creation branch was never exercised — which
    is how a swallowed ``QuestionNotFoundError`` survived: accepting a
    candidate whose question code was absent from the catalog silently marked
    it ACCEPTED and wrote no answer at all.
    """

    @staticmethod
    def _seed_question(session_factory, catalog_id: str, question_code: str) -> None:
        with session_factory() as session:
            section_id = str(uuid.uuid4())
            session.add(
                CatalogSection(
                    id=section_id,
                    release_id=catalog_id,
                    section_code=f"APPLICATION_{question_code}",
                    display_name=f"Application {question_code}",
                    display_order=1,
                )
            )
            session.flush()
            session.add(
                CatalogQuestion(
                    id=str(uuid.uuid4()),
                    section_id=section_id,
                    question_code=question_code,
                    question_text="Free text question",
                    response_type="TEXT",
                    required_level="REQUIRED",
                    collection_mode="AUTO_IMPORT",
                    display_order=1,
                    is_active=True,
                    response_schema_version="1.0",
                )
            )
            session.commit()

    def _service(self, session_factory) -> CandidateService:
        return CandidateService(session_factory, answer_service=AnswerService(session_factory))

    def test_target_absent_from_catalog_raises_and_leaves_candidate_proposed(
        self, session_factory, actor_context: ActorContext
    ) -> None:
        """The candidate must not be marked ACCEPTED when no answer can be written."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(
            session_factory,
            prereqs,
            target_key="Q-DOES-NOT-EXIST",
        )
        service = self._service(session_factory)

        with pytest.raises(CandidateTargetNotInCatalogError):
            service.accept_candidate(candidate_id, actor_context)

        assert service.get_candidate(candidate_id)["state"] == "PROPOSED"

    def test_target_in_catalog_creates_answer_and_evidence_link(
        self, session_factory, actor_context: ActorContext
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)
        service = self._service(session_factory)

        result = service.accept_candidate(candidate_id, actor_context)

        assert result["state"] == "ACCEPTED"
        assert result["answer_revision_id"] is not None

    def test_accept_people_list_candidate_normalizes_legacy_string_entries(
        self, session_factory, actor_context: ActorContext
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        self._seed_question(session_factory, prereqs["catalog_id"], "APP-002")
        with session_factory() as session:
            question = session.execute(
                select(CatalogQuestion).where(CatalogQuestion.question_code == "APP-002")
            ).scalar_one()
            question.response_type = "PEOPLE_LIST"
            session.commit()
        candidate_id = _create_candidate(
            session_factory,
            prereqs,
            target_key="APP-002",
        )
        with session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            assert candidate is not None
            candidate.raw_value_json = {"people": ["Jane Doe"]}
            session.commit()

        result = self._service(session_factory).accept_candidate(candidate_id, actor_context)

        assert result["state"] == "ACCEPTED"
        with session_factory() as session:
            answer = session.query(AnswerInstance).one()
            revision = session.get(AnswerRevision, answer.current_rev_id)
            assert revision is not None
            assert revision.response_json == {
                "people": [{"name": "Jane Doe", "role_code": "UNKNOWN"}]
            }

    def test_accept_with_edit_target_absent_raises_and_leaves_candidate_proposed(
        self, session_factory, actor_context: ActorContext
    ) -> None:
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(
            session_factory,
            prereqs,
            target_key="Q-DOES-NOT-EXIST",
        )
        service = self._service(session_factory)

        with pytest.raises(CandidateTargetNotInCatalogError):
            service.accept_with_edit(
                candidate_id,
                {"text": "Edited value"},
                actor_context,
            )

        assert service.get_candidate(candidate_id)["state"] == "PROPOSED"

    def test_accept_candidate_rolls_back_when_disposition_cas_conflicts(
        self, session_factory, actor_context: ActorContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Answer revision and evidence link must roll back when CAS disposition fails."""
        prereqs = _seed_prerequisites(session_factory)
        candidate_id = _create_candidate(session_factory, prereqs)
        service = self._service(session_factory)

        original_compare_and_set = CandidateRepository.compare_and_set_state

        def conflict_once(self, **kwargs):  # type: ignore[no-untyped-def]
            return False

        monkeypatch.setattr(
            CandidateRepository,
            "compare_and_set_state",
            conflict_once,
        )

        with pytest.raises(ConcurrencyConflictError):
            service.accept_candidate(candidate_id, actor_context)

        monkeypatch.setattr(
            CandidateRepository,
            "compare_and_set_state",
            original_compare_and_set,
        )

        with session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            assert candidate is not None
            assert candidate.state == "PROPOSED"
            assert session.query(AnswerInstance).count() == 0
            assert session.query(AnswerEvidenceLink).count() == 0
