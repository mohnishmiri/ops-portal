"""
Answer service commands — A02 + A02b.

Implements SaveAnswer, ClearAnswer, ConfirmAnswer, and MarkNotApplicable
following Architecture sections 25.2 and 27.3.

A02b enhancements:
- Registry-based type resolution using get_default_registry()
- is_computed check for blocking direct saves
- Semantic no-op detection using compare()
- Optimistic concurrency with expected_version
- Response schema version and change reason persistence

Architecture rules applied here:
- Receives validated commands; does NOT parse HTTP or read env vars.
- Loads state through repositories inside a UoW.
- Invokes domain policies (state checks, type checks, value checks).
- Commits through UoW.
- Returns detached plain dicts — no ORM entities leave this module.
- Audit events use ``event_code`` (the ORM column name).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    ClearReasonRequiredError,
    ConcurrencyConflictError,
    IntakeNotOpenError,
    InvalidResponseError,
    InvalidResponseTypeError,
    NoCurrentRevisionError,
    QuestionNotFoundError,
    RationaleRequiredError,
)
from migration_intake.catalog.response_types import get_default_registry
from migration_intake.persistence.models import Actor, AuditEvent
from migration_intake.persistence.unit_of_work import UnitOfWork, uow_context

# States in which an intake accepts new answers.
_OPEN_INTAKE_STATES: frozenset[str] = frozenset(
    {
        "DRAFT",
        "COLLECTING",
        "IN_REVIEW",
        "CHANGES_REQUESTED",
        "READY_TO_FREEZE",
    }
)


# ---------------------------------------------------------------------------
# Private helpers (mirrors the pattern in applications.py)
# ---------------------------------------------------------------------------


def _ensure_actor(uow: UnitOfWork, actor: ActorContext, now: datetime) -> None:
    """Insert the actor row if it does not already exist."""
    from sqlalchemy import select

    stmt = select(Actor).where(Actor.id == actor.actor_id)
    existing = uow._session.execute(stmt).scalar_one_or_none()
    if existing is None:
        actor_row = Actor(
            id=actor.actor_id,
            display_name=actor.display_name or "Unknown",
            attuid=None,
            created_at=now,
        )
        uow._session.add(actor_row)
        uow._session.flush()


def _write_audit(
    uow: UnitOfWork,
    actor: ActorContext,
    event_code: str,
    entity_type: str,
    entity_id: str,
    now: datetime,
) -> None:
    """Append an immutable audit event row to the current transaction."""
    audit = AuditEvent(
        id=str(uuid.uuid4()),
        entity_type=entity_type,
        entity_id=entity_id,
        event_code=event_code,
        actor_id=actor.actor_id,
        occurred_at=now,
        payload=None,
    )
    uow._session.add(audit)
    uow._session.flush()


def _resolve_question(uow: UnitOfWork, intake_id: str, question_code: str) -> dict:
    """
    Load the intake and question; apply intake-open and question-found checks.

    Returns (intake_dict, question_dict).
    Raises IntakeNotOpenError or QuestionNotFoundError as appropriate.
    """
    intake = uow.intakes.get(intake_id)
    if intake is None or intake["state"] not in _OPEN_INTAKE_STATES:
        state = intake["state"] if intake else "NOT_FOUND"
        raise IntakeNotOpenError(
            f"Intake {intake_id!r} is in state {state!r}; "
            "answers can only be saved to open intakes"
        )

    question = uow.catalogs.get_question_by_code(
        intake["catalog_id"], question_code
    )
    if question is None:
        raise QuestionNotFoundError(
            f"Question code {question_code!r} not found in catalog "
            f"{intake['catalog_id']!r}"
        )

    return intake, question


def _get_or_create_instance(
    uow: UnitOfWork, intake_id: str, question_id: str, now: datetime
) -> tuple[str, bool]:
    """
    Return the answer instance_id for (intake_id, question_id).

    Creates the instance row if it does not already exist.
    Returns (instance_id, created: bool).
    """
    existing = uow.answers.get_instance(intake_id, question_id)
    if existing is not None:
        return existing["id"], False

    instance_id = str(uuid.uuid4())
    uow.answers.add_instance(
        instance_id=instance_id,
        intake_id=intake_id,
        question_id=question_id,
        created_at=now,
    )
    return instance_id, True


def _next_revision_number(uow: UnitOfWork, instance_id: str) -> int:
    """Return the next revision number (current max + 1, or 1 for first)."""
    revisions = uow.answers.get_revisions(instance_id)
    if not revisions:
        return 1
    return max(r["revision_number"] for r in revisions) + 1


def _append_revision(
    uow: UnitOfWork,
    instance_id: str,
    response_json: dict,
    confirm_state: str,
    actor: ActorContext,
    now: datetime,
    response_schema_version: str | None = None,
    change_reason: str | None = None,
    evidence_references: list[str] | None = None,
) -> tuple[str, int]:
    """
    Create an append-only revision and advance the current pointer.

    Returns (revision_id, revision_number).
    """
    revision_id = str(uuid.uuid4())
    rev_number = _next_revision_number(uow, instance_id)

    uow.answers.add_revision(
        revision_id=revision_id,
        instance_id=instance_id,
        revision_number=rev_number,
        response_json=response_json,
        confirm_state=confirm_state,
        authored_at=now,
        authored_by_id=actor.actor_id,
        response_schema_version=response_schema_version,
        change_reason=change_reason,
    )

    if evidence_references:
        from migration_intake.persistence.models_candidates import AnswerEvidenceLink

        for evidence_item_id in evidence_references:
            uow._session.add(
                AnswerEvidenceLink(
                    id=str(uuid.uuid4()),
                    revision_id=revision_id,
                    evidence_item_id=evidence_item_id,
                    candidate_id=None,
                    link_type="CONFIRMATION_CARRY_FORWARD",
                    source_locator=None,
                    created_at=now,
                )
            )
        uow._session.flush()

    # Determine value_state based on confirm_state
    value_state = "FILLED" if response_json else "EMPTY"
    if confirm_state == "CLEARED":
        value_state = "EMPTY"
    elif confirm_state == "NOT_APPLICABLE":
        value_state = "NOT_APPLICABLE"

    # Determine review_state based on confirm_state
    review_state = "UNREVIEWED"
    if confirm_state == "CONFIRMED":
        review_state = "CONFIRMED"
    elif confirm_state == "NOT_APPLICABLE":
        review_state = "NOT_APPLICABLE"

    uow.answers.advance_current_pointer(
        instance_id,
        revision_id,
        updated_at=now,
        value_state=value_state,
        review_state=review_state,
    )

    return revision_id, rev_number


def _save_answer_in_uow(
    *,
    uow: UnitOfWork,
    intake_id: str,
    question_code: str,
    response_json: dict,
    actor: ActorContext,
    expected_version: int | None = None,
    change_reason: str = "",
    response_schema_version: str | None = None,
) -> dict:
    """Save an answer inside an existing UnitOfWork without committing."""
    now = datetime.now(tz=UTC)

    if response_json is None or not isinstance(response_json, dict):
        raise InvalidResponseError("response_json must be a non-None dict")

    intake, question = _resolve_question(uow, intake_id, question_code)

    response_type_code = question["response_type"]
    registry = get_default_registry()
    response_type = registry.get(response_type_code)
    blocked_response_types = frozenset({"COMPUTED", "REGISTER"})

    if response_type is not None and response_type.is_computed:
        raise InvalidResponseTypeError(
            f"Question {question_code!r} has response_type "
            f"{response_type_code!r} (is_computed=True); cannot be directly saved"
        )
    if response_type is None and response_type_code in blocked_response_types:
        raise InvalidResponseTypeError(
            f"Question {question_code!r} has response_type "
            f"{response_type_code!r}; cannot be directly saved"
        )

    _ensure_actor(uow, actor, now)
    instance_id, created = _get_or_create_instance(uow, intake_id, question["id"], now)

    current = uow.answers.get_current_revision(instance_id)
    current_version = current["revision_number"] if current else 0
    if expected_version is not None and current_version != expected_version:
        raise ConcurrencyConflictError(
            f"Answer concurrency conflict: expected version {expected_version}, "
            f"but current version is {current_version}"
        )

    if current is not None:
        old_value = current["response_json"]
        if response_type is not None:
            comparison = response_type.compare(old_value or {}, response_json or {})
            if comparison.is_equal:
                return {"changed": False}
        elif old_value == response_json:
            return {"changed": False}

    revision_id, rev_number = _append_revision(
        uow,
        instance_id,
        response_json,
        "DRAFT",
        actor,
        now,
        response_schema_version=response_schema_version,
        change_reason=change_reason if change_reason else None,
    )

    _write_audit(
        uow, actor, "ANSWER_SAVED", "answer_instance", instance_id, now
    )

    return {
        "changed": True,
        "revision_number": rev_number,
        "instance_id": instance_id,
        "revision_id": revision_id,
        "created": created,
        "intake_id": intake["id"],
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AnswerService:
    """
    Coordinates answer use cases (A02): save, clear, confirm, mark N/A.

    Each public method opens exactly one UoW, performs all reads and writes
    inside it, commits on success, and returns a plain dict.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # save_answer  (section 25.2)
    # ------------------------------------------------------------------

    def save_answer(
        self,
        intake_id: str,
        question_code: str,
        response_json: dict,
        actor: ActorContext,
        expected_version: int | None = None,
        change_reason: str = "",
        response_schema_version: str | None = None,
    ) -> dict:
        """
        Save a human-authored answer for a catalog question.

        A02b enhancements:
        - Registry-based type resolution using get_default_registry()
        - is_computed check for blocking direct saves
        - Semantic no-op detection using compare()
        - Optimistic concurrency with expected_version
        - Response schema version and change reason persistence

        Steps:
        1. Load intake; confirm state is open → IntakeNotOpenError.
        2. Load question by code → QuestionNotFoundError.
        3. Resolve type through registry; reject is_computed=True → InvalidResponseTypeError.
        4. Validate response payload (must be a non-None dict) → InvalidResponseError.
        5. Get or create AnswerInstance.
        6. Check expected_version for concurrency control → ConcurrencyConflictError.
        7. Normalize and compare for semantic no-op detection.
        8. Create append-only revision with schema version and change reason.
        9. Advance current pointer.
        10. Write ANSWER_SAVED audit event.
        11. Commit and return result.
        """
        with uow_context(self._session_factory) as uow:
            result = self.save_answer_in_uow(
                uow=uow,
                intake_id=intake_id,
                question_code=question_code,
                response_json=response_json,
                actor=actor,
                expected_version=expected_version,
                change_reason=change_reason,
                response_schema_version=response_schema_version,
            )
            uow.commit()
            return result

    def save_answer_in_uow(
        self,
        *,
        uow: UnitOfWork,
        intake_id: str,
        question_code: str,
        response_json: dict,
        actor: ActorContext,
        expected_version: int | None = None,
        change_reason: str = "",
        response_schema_version: str | None = None,
    ) -> dict:
        """
        Save an answer using a caller-owned UnitOfWork.

        This method never commits. It is intended for orchestration services
        that must mutate answers and related tables atomically.
        """
        return _save_answer_in_uow(
            uow=uow,
            intake_id=intake_id,
            question_code=question_code,
            response_json=response_json,
            actor=actor,
            expected_version=expected_version,
            change_reason=change_reason,
            response_schema_version=response_schema_version,
        )

    # ------------------------------------------------------------------
    # clear_answer  (section 25.2)
    # ------------------------------------------------------------------

    def clear_answer(
        self,
        intake_id: str,
        question_code: str,
        actor: ActorContext,
        reason: str = "",
    ) -> dict:
        """
        Clear (blank) a previously saved answer.

        - Named command; does NOT simply save an empty value.
        - If the current revision is CONFIRMED, a non-empty reason is required.
        - Creates a new revision with response_json={} and confirm_state=CLEARED.
        - Never deletes revisions.
        """
        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            intake, question = _resolve_question(uow, intake_id, question_code)
            _ensure_actor(uow, actor, now)

            instance_id, _ = _get_or_create_instance(
                uow, intake_id, question["id"], now
            )

            current = uow.answers.get_current_revision(instance_id)

            # If the current revision is CONFIRMED, require a reason.
            if current is not None and current["confirm_state"] == "CONFIRMED":
                if not reason or not reason.strip():
                    raise ClearReasonRequiredError(
                        "Clearing a confirmed answer requires a non-empty reason"
                    )

            _, rev_number = _append_revision(
                uow, instance_id, {}, "CLEARED", actor, now
            )

            _write_audit(
                uow, actor, "ANSWER_CLEARED", "answer_instance", instance_id, now
            )

            uow.commit()

        return {"changed": True, "revision_number": rev_number}

    # ------------------------------------------------------------------
    # confirm_answer  (section 25.2)
    # ------------------------------------------------------------------

    def confirm_answer(
        self,
        intake_id: str,
        question_code: str,
        actor: ActorContext,
        rationale: str = "",
    ) -> dict:
        """
        Mark the current answer revision as confirmed.

        - Requires a current revision to exist → NoCurrentRevisionError.
        - Creates a new revision with confirm_state=CONFIRMED, same response_json.
        - Records actor and rationale in an ANSWER_CONFIRMED audit event.
        """
        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            intake, question = _resolve_question(uow, intake_id, question_code)
            _ensure_actor(uow, actor, now)

            # Peek at the existing instance (do not create one here).
            existing = uow.answers.get_instance(intake_id, question["id"])
            if existing is None:
                raise NoCurrentRevisionError(
                    f"No answer instance for question {question_code!r} "
                    f"in intake {intake_id!r}; save an answer first"
                )

            instance_id = existing["id"]
            current = uow.answers.get_current_revision(instance_id)
            if current is None:
                raise NoCurrentRevisionError(
                    f"Answer instance {instance_id!r} has no current revision"
                )

            _, rev_number = _append_revision(
                uow,
                instance_id,
                current["response_json"],
                "CONFIRMED",
                actor,
                now,
                response_schema_version=current["response_schema_version"],
                change_reason=rationale.strip() or "ANSWER_CONFIRMED",
                evidence_references=uow.answers.get_provenance_references_for_revision(
                    current["id"]
                ),
            )

            _write_audit(
                uow,
                actor,
                "ANSWER_CONFIRMED",
                "answer_instance",
                instance_id,
                now,
            )

            uow.commit()

        return {"confirmed": True, "revision_number": rev_number}

    # ------------------------------------------------------------------
    # mark_not_applicable  (section 25.2)
    # ------------------------------------------------------------------

    def mark_not_applicable(
        self,
        intake_id: str,
        question_code: str,
        actor: ActorContext,
        rationale: str,
    ) -> dict:
        """
        Mark a question as not applicable for this intake.

        - Requires a non-empty rationale → RationaleRequiredError.
        - Creates an append-only revision with confirm_state=NOT_APPLICABLE
          and response_json={}.
        """
        now = datetime.now(tz=UTC)

        if not rationale or not rationale.strip():
            raise RationaleRequiredError(
                "mark_not_applicable requires a non-empty rationale"
            )

        with uow_context(self._session_factory) as uow:
            intake, question = _resolve_question(uow, intake_id, question_code)
            _ensure_actor(uow, actor, now)

            instance_id, _ = _get_or_create_instance(
                uow, intake_id, question["id"], now
            )

            _, rev_number = _append_revision(
                uow, instance_id, {}, "NOT_APPLICABLE", actor, now
            )

            _write_audit(
                uow,
                actor,
                "ANSWER_NOT_APPLICABLE",
                "answer_instance",
                instance_id,
                now,
            )

            uow.commit()

        return {"changed": True, "revision_number": rev_number}
