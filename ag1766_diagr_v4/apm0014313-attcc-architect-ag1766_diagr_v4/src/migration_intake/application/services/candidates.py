"""
Candidate application service (A04).

Implements accept, accept-with-edit, reject, and defer operations
for candidates extracted from evidence imports.

Architecture (section 25.4):
1. Validate candidate state and version (optimistic concurrency).
2. Validate intake is open for editing.
3. For acceptance: delegate to answer service, record evidence linkage.
4. For rejection: require reason, never change canonical state.
5. For defer: record reason and assignment context.
6. Update candidate disposition atomically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker  # noqa: TC002

from migration_intake.application.dto import ActorContext  # noqa: TC001
from migration_intake.application.errors import (
    ConcurrencyConflictError,
    IntakeNotOpenError,
)
from migration_intake.application.services.answers import AnswerService  # noqa: TC001
from migration_intake.imports.legacy_intake_mappings_v1 import canonical_target_key
from migration_intake.persistence.models import (
    CatalogQuestion,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.unit_of_work import uow_context


class CandidateNotFoundError(Exception):
    """Raised when a candidate is not found."""

    pass


class CandidateNotProposedError(Exception):
    """Raised when trying to act on a candidate that is not in PROPOSED state."""

    pass


class RejectReasonRequiredError(Exception):
    """Raised when rejecting without a reason."""

    pass


class DeferReasonRequiredError(Exception):
    """Raised when deferring without a reason."""

    pass


class CandidateTargetNotInCatalogError(Exception):
    """
    Raised when accepting a question candidate whose code is not in the catalog.

    Accepting such a candidate cannot produce an answer, so it must fail
    loudly and leave the candidate PROPOSED. Marking it ACCEPTED while
    writing nothing looks successful to the reviewer and silently loses the
    proposal — which is how mis-targeted importers (for example an adapter
    emitting positional keys rather than catalog question codes) stay hidden.
    """

    pass


class NonQuestionCandidateError(Exception):
    """
    Raised when attempting to accept a non-QUESTION candidate as a questionnaire answer.

    Non-question candidates (INTERFACE_REGISTER, WAVEUTIL_ROW, provisioning reference
    data, etc.) cannot be accepted through the standard question-answer workflow.
    They require specialized acceptance workflows or are informational only.
    """

    pass


class CandidateService:
    """
    Coordinates candidate review operations (A04).

    Each public method opens exactly one session, performs all reads and writes
    inside it, commits on success, and returns a plain dict.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        answer_service: AnswerService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._answer_service = answer_service

    # ------------------------------------------------------------------
    # accept_candidate
    # ------------------------------------------------------------------

    def accept_candidate(
        self,
        candidate_id: str,
        actor: ActorContext,
        expected_version: int | None = None,
        rationale: str = "",
    ) -> dict[str, Any]:
        """
        Accept a candidate, creating a canonical answer from its value.

        Steps:
        1. Load candidate; confirm state is PROPOSED.
        2. Check expected_version for concurrency control.
        3. Load intake; confirm state allows editing.
        4. Delegate to answer service to create/update canonical answer.
        5. Create evidence link from answer revision to candidate's evidence.
        6. Update candidate state to ACCEPTED.
        7. Commit and return result.

        Args:
            candidate_id: UUID string of the candidate.
            actor: Actor performing the operation.
            expected_version: Optional version for optimistic concurrency.
            rationale: Optional reason for acceptance.

        Returns:
            Dict with candidate_id, state, answer_revision_id.

        Raises:
            CandidateNotFoundError: Candidate not found.
            CandidateNotProposedError: Candidate not in PROPOSED state.
            ConcurrencyConflictError: Version mismatch.
            IntakeNotOpenError: Intake is not open for editing.
        """
        with uow_context(self._session_factory) as uow:
            session = uow._session
            repo = CandidateRepository(session)

            candidate = repo.get_by_id(candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"Candidate {candidate_id} not found")
            if candidate.state != "PROPOSED":
                raise CandidateNotProposedError(
                    f"Candidate {candidate_id} is in state {candidate.state}, not PROPOSED"
                )
            if expected_version is not None and candidate.row_version != expected_version:
                raise ConcurrencyConflictError(
                    f"Version mismatch: expected {expected_version}, got {candidate.row_version}"
                )

            intake = session.execute(
                select(Intake).where(Intake.id == candidate.intake_id)
            ).scalar_one_or_none()
            if intake is None or intake.state not in ("DRAFT", "IN_PROGRESS"):
                raise IntakeNotOpenError(f"Intake {candidate.intake_id} is not open for editing")
            if candidate.target_kind != "QUESTION":
                raise NonQuestionCandidateError(
                    f"Candidate {candidate_id} has target_kind={candidate.target_kind!r}; "
                    f"only QUESTION candidates can be accepted as questionnaire answers"
                )

            question_code = self._resolve_question_target(
                session=session,
                candidate=candidate,
            )

            answer_revision_id = None
            if self._answer_service is not None:
                response_json = candidate.normalized_value_json or candidate.raw_value_json or {}
                response_json = self._merge_collection_candidate(
                    session,
                    candidate,
                    question_code,
                    response_json,
                )
                answer_result = self._answer_service.save_answer_in_uow(
                    uow=uow,
                    intake_id=str(candidate.intake_id),
                    question_code=question_code,
                    response_json=response_json,
                    actor=actor,
                    change_reason=f"Accepted from candidate {candidate_id}",
                )
                answer_revision_id = answer_result.get("revision_id")
                if answer_revision_id:
                    repo.create_evidence_link(
                        revision_id=answer_revision_id,
                        evidence_item_id=str(candidate.evidence_item_id),
                        link_type="IMPORT_ACCEPTANCE",
                        candidate_id=candidate_id,
                    )

            now = datetime.now(tz=UTC)
            updated = repo.compare_and_set_state(
                candidate_id=candidate_id,
                expected_row_version=int(candidate.row_version),
                expected_state="PROPOSED",
                new_state="ACCEPTED",
                decided_by_id=actor.actor_id,
                decided_at=now,
                decision_rationale=rationale,
            )
            if not updated:
                raise ConcurrencyConflictError(
                    "Candidate decision conflict: candidate was modified by another reviewer"
                )

            uow.commit()
            return {
                "candidate_id": candidate_id,
                "state": "ACCEPTED",
                "answer_revision_id": answer_revision_id,
            }

    @staticmethod
    def _merge_collection_candidate(
        session: Session,
        candidate: Candidate,
        question_code: str,
        response_json: dict[str, Any],
    ) -> dict[str, Any]:
        """Combine accepted collection candidates into the current answer."""
        question = session.execute(
            select(CatalogQuestion)
            .join(CatalogSection, CatalogSection.id == CatalogQuestion.section_id)
            .join(Intake, Intake.catalog_id == CatalogSection.release_id)
            .where(
                CatalogQuestion.question_code == question_code,
                Intake.id == candidate.intake_id,
            )
        ).scalar_one_or_none()
        if question is None or question.response_type not in {
            "PEOPLE_LIST",
            "MULTI_SELECT",
            "MEASUREMENT_SET",
        }:
            return response_json

        accepted_candidates = (
            session.execute(
                select(Candidate)
                .where(
                    Candidate.intake_id == candidate.intake_id,
                    Candidate.target_kind == "QUESTION",
                    Candidate.target_key == question_code,
                    Candidate.state == "ACCEPTED",
                )
                .order_by(Candidate.created_at.asc())
            )
            .scalars()
            .all()
        )

        if question.response_type == "MULTI_SELECT":
            values: list[Any] = []
            payloads = [
                item.normalized_value_json or item.raw_value_json or {}
                for item in accepted_candidates
            ]
            payloads.append(response_json)
            for payload in payloads:
                values.extend(payload.get("values", payload.get("selected", [])) or [])
            return {"values": list(dict.fromkeys(values))}

        if question.response_type == "MEASUREMENT_SET":
            measurements: list[dict[str, Any]] = []
            payloads = [
                item.normalized_value_json or item.raw_value_json or {}
                for item in accepted_candidates
            ]
            payloads.append(response_json)
            for payload in payloads:
                measurements.extend(payload.get("measurements", []) or [])
            return {
                "measurements": list(
                    {
                        item.get("metric"): item for item in measurements if item.get("metric")
                    }.values()
                )
            }

        existing_people: list[dict[str, Any]] = []
        seen = {
            (person.get("attuid"), person.get("email"), person.get("name"))
            for person in existing_people
        }
        payloads = [
            item.normalized_value_json or item.raw_value_json or {} for item in accepted_candidates
        ]
        payloads.append(response_json)
        for payload in payloads:
            for person in payload.get("people", []) or []:
                if isinstance(person, str) and person.strip():
                    person = {"name": person.strip(), "role_code": "UNKNOWN"}
                if not isinstance(person, dict):
                    continue
                key = (person.get("attuid"), person.get("email"), person.get("name"))
                if key not in seen:
                    existing_people.append(person)
                    seen.add(key)
        return {"people": existing_people}

    # ------------------------------------------------------------------
    # accept_with_edit
    # ------------------------------------------------------------------

    def accept_with_edit(
        self,
        candidate_id: str,
        edited_value: dict[str, Any],
        actor: ActorContext,
        expected_version: int | None = None,
        rationale: str = "",
    ) -> dict[str, Any]:
        """
        Accept a candidate with an edited value.

        The original raw value is preserved; the edited value is stored
        in accepted_value_json and used for the canonical answer.

        Args:
            candidate_id: UUID string of the candidate.
            edited_value: The edited value to use for the answer.
            actor: Actor performing the operation.
            expected_version: Optional version for optimistic concurrency.
            rationale: Optional reason for acceptance with edit.

        Returns:
            Dict with candidate_id, state, answer_revision_id.
        """
        with uow_context(self._session_factory) as uow:
            session = uow._session
            repo = CandidateRepository(session)

            candidate = repo.get_by_id(candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"Candidate {candidate_id} not found")
            if candidate.state != "PROPOSED":
                raise CandidateNotProposedError(
                    f"Candidate {candidate_id} is in state {candidate.state}, not PROPOSED"
                )
            if expected_version is not None and candidate.row_version != expected_version:
                raise ConcurrencyConflictError(
                    f"Version mismatch: expected {expected_version}, got {candidate.row_version}"
                )

            intake = session.execute(
                select(Intake).where(Intake.id == candidate.intake_id)
            ).scalar_one_or_none()
            if intake is None or intake.state not in ("DRAFT", "IN_PROGRESS"):
                raise IntakeNotOpenError(f"Intake {candidate.intake_id} is not open for editing")
            if candidate.target_kind != "QUESTION":
                raise NonQuestionCandidateError(
                    f"Candidate {candidate_id} has target_kind={candidate.target_kind!r}; "
                    f"only QUESTION candidates can be accepted as questionnaire answers"
                )

            question_code = self._resolve_question_target(
                session=session,
                candidate=candidate,
            )

            answer_revision_id = None
            if self._answer_service is not None:
                result = self._answer_service.save_answer_in_uow(
                    uow=uow,
                    intake_id=str(candidate.intake_id),
                    question_code=question_code,
                    response_json=edited_value,
                    actor=actor,
                    change_reason=f"Accepted with edit from candidate {candidate_id}",
                )
                answer_revision_id = result.get("revision_id")
                if answer_revision_id:
                    repo.create_evidence_link(
                        revision_id=answer_revision_id,
                        evidence_item_id=str(candidate.evidence_item_id),
                        link_type="IMPORT_ACCEPTANCE",
                        candidate_id=candidate_id,
                    )

            now = datetime.now(tz=UTC)
            updated = repo.compare_and_set_state(
                candidate_id=candidate_id,
                expected_row_version=int(candidate.row_version),
                expected_state="PROPOSED",
                new_state="ACCEPTED_WITH_EDIT",
                decided_by_id=actor.actor_id,
                decided_at=now,
                decision_rationale=rationale,
                accepted_value_json=edited_value,
            )
            if not updated:
                raise ConcurrencyConflictError(
                    "Candidate decision conflict: candidate was modified by another reviewer"
                )

            uow.commit()
            return {
                "candidate_id": candidate_id,
                "state": "ACCEPTED_WITH_EDIT",
                "answer_revision_id": answer_revision_id,
            }

    # ------------------------------------------------------------------
    # reject_candidate
    # ------------------------------------------------------------------

    def reject_candidate(
        self,
        candidate_id: str,
        reason: str,
        actor: ActorContext,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Reject a candidate.

        Rejection requires a reason and never changes canonical state.

        Args:
            candidate_id: UUID string of the candidate.
            reason: Required reason for rejection.
            actor: Actor performing the operation.
            expected_version: Optional version for optimistic concurrency.

        Returns:
            Dict with candidate_id, state.

        Raises:
            RejectReasonRequiredError: No reason provided.
        """
        if not reason or not reason.strip():
            raise RejectReasonRequiredError("Rejection requires a reason")

        with uow_context(self._session_factory) as uow:
            repo = CandidateRepository(uow._session)

            candidate = repo.get_by_id(candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"Candidate {candidate_id} not found")
            if candidate.state != "PROPOSED":
                raise CandidateNotProposedError(
                    f"Candidate {candidate_id} is in state {candidate.state}, not PROPOSED"
                )
            if expected_version is not None and candidate.row_version != expected_version:
                raise ConcurrencyConflictError(
                    f"Version mismatch: expected {expected_version}, got {candidate.row_version}"
                )

            now = datetime.now(tz=UTC)
            updated = repo.compare_and_set_state(
                candidate_id=candidate_id,
                expected_row_version=int(candidate.row_version),
                expected_state="PROPOSED",
                new_state="REJECTED",
                decided_by_id=actor.actor_id,
                decided_at=now,
                decision_rationale=reason,
            )
            if not updated:
                raise ConcurrencyConflictError(
                    "Candidate decision conflict: candidate was modified by another reviewer"
                )
            uow.commit()
            return {
                "candidate_id": candidate_id,
                "state": "REJECTED",
            }

    # ------------------------------------------------------------------
    # defer_candidate
    # ------------------------------------------------------------------

    def defer_candidate(
        self,
        candidate_id: str,
        reason: str,
        actor: ActorContext,
        expected_version: int | None = None,
        assigned_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Defer a candidate for later review.

        Deferral records reason and optional assignment context.
        Deferred candidates remain a readiness blocker.

        Args:
            candidate_id: UUID string of the candidate.
            reason: Required reason for deferral.
            actor: Actor performing the operation.
            expected_version: Optional version for optimistic concurrency.
            assigned_to: Optional actor ID to assign for follow-up.

        Returns:
            Dict with candidate_id, state.

        Raises:
            DeferReasonRequiredError: No reason provided.
        """
        if not reason or not reason.strip():
            raise DeferReasonRequiredError("Deferral requires a reason")

        with uow_context(self._session_factory) as uow:
            repo = CandidateRepository(uow._session)

            candidate = repo.get_by_id(candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"Candidate {candidate_id} not found")
            if candidate.state != "PROPOSED":
                raise CandidateNotProposedError(
                    f"Candidate {candidate_id} is in state {candidate.state}, not PROPOSED"
                )
            if expected_version is not None and candidate.row_version != expected_version:
                raise ConcurrencyConflictError(
                    f"Version mismatch: expected {expected_version}, got {candidate.row_version}"
                )

            decision_rationale = f"{reason} [Assigned to: {assigned_to}]" if assigned_to else reason
            now = datetime.now(tz=UTC)
            updated = repo.compare_and_set_state(
                candidate_id=candidate_id,
                expected_row_version=int(candidate.row_version),
                expected_state="PROPOSED",
                new_state="DEFERRED",
                decided_by_id=actor.actor_id,
                decided_at=now,
                decision_rationale=decision_rationale,
            )
            if not updated:
                raise ConcurrencyConflictError(
                    "Candidate decision conflict: candidate was modified by another reviewer"
                )
            uow.commit()
            return {
                "candidate_id": candidate_id,
                "state": "DEFERRED",
                "assigned_to": assigned_to,
            }

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        """Get a candidate by ID."""
        session = self._session_factory()
        try:
            repo = CandidateRepository(session)
            candidate = repo.get_by_id(candidate_id)
            if candidate is None:
                return None
            return self._candidate_to_dict(candidate)
        finally:
            session.close()

    def list_candidates_for_intake(
        self,
        intake_id: str,
        state: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List candidates for an intake."""
        session = self._session_factory()
        try:
            repo = CandidateRepository(session)
            candidates = repo.get_by_intake(intake_id, state=state, limit=limit, offset=offset)
            return [self._candidate_to_dict(c) for c in candidates]
        finally:
            session.close()

    def count_candidates_for_intake(
        self,
        intake_id: str,
        state: str | None = None,
    ) -> int:
        """Count candidates for an intake."""
        session = self._session_factory()
        try:
            repo = CandidateRepository(session)
            return repo.count_by_intake(intake_id, state=state)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_question_target(
        self,
        *,
        session: Session,
        candidate: Candidate,
    ) -> str:
        """Resolve and validate the target question code against the pinned catalog."""
        question_code = canonical_target_key(self._extract_question_code(candidate.target_key))
        if not question_code:
            raise CandidateTargetNotInCatalogError(
                f"Candidate {candidate.id} has no resolvable question code in target key "
                f"{candidate.target_key!r}"
            )

        catalog_match = session.execute(
            select(CatalogQuestion.id)
            .join(CatalogSection, CatalogSection.id == CatalogQuestion.section_id)
            .join(Intake, Intake.catalog_id == CatalogSection.release_id)
            .where(
                Intake.id == candidate.intake_id,
                CatalogQuestion.question_code == question_code,
            )
        ).scalar_one_or_none()
        if catalog_match is None:
            raise CandidateTargetNotInCatalogError(
                f"Candidate {candidate.id} targets question {question_code!r}, which does not "
                "exist in this intake's pinned catalog release"
            )

        return question_code

    @staticmethod
    def _extract_question_code(target_key: str) -> str | None:
        """Extract question code from target key."""
        # Target keys are formatted as PREFIX-CODE or just CODE
        # Examples: APP-001, Q-001, TSS-MANUFACTURER
        if not target_key:
            return None
        # Return the full target key as the question code
        # The answer service will handle mapping
        return target_key

    @staticmethod
    def _candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
        """Convert a Candidate model to a dict."""
        return {
            "id": str(candidate.id),
            "import_run_id": str(candidate.import_run_id),
            "application_id": str(candidate.application_id),
            "intake_id": str(candidate.intake_id),
            "evidence_item_id": str(candidate.evidence_item_id),
            "target_kind": candidate.target_kind,
            "target_key": candidate.target_key,
            "origin": candidate.origin,
            "raw_value_json": candidate.raw_value_json,
            "normalized_value_json": candidate.normalized_value_json,
            "scope_json": candidate.scope_json,
            "accepted_value_json": candidate.accepted_value_json,
            "confidence": candidate.confidence,
            "state": candidate.state,
            "row_version": candidate.row_version,
            "created_at": (
                candidate.created_at.isoformat()
                if candidate.created_at and hasattr(candidate.created_at, "isoformat")
                else candidate.created_at
            ),
            "decided_by_id": str(candidate.decided_by_id) if candidate.decided_by_id else None,
            "decided_at": (
                candidate.decided_at.isoformat()
                if candidate.decided_at and hasattr(candidate.decided_at, "isoformat")
                else candidate.decided_at
            ),
            "decision_rationale": candidate.decision_rationale,
        }
