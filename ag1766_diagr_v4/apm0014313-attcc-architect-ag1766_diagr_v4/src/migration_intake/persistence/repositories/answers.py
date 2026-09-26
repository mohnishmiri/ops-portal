"""
AnswerRepository — P04 (Repositories and Unit of Work).

Answer persistence follows the append-only revision pattern described in
Architecture section 32:

  1. Insert AnswerInstance with current_rev_id=NULL (breaks the circular FK).
  2. Insert AnswerRevision pointing back to the instance.
  3. Update AnswerInstance.current_rev_id to point at the new revision.

The UNIQUE(instance_id, revision_number) constraint on ans_revisions
enforces the append-only guarantee at the database level.

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- advance_current_pointer uses a core UPDATE; the identity-map entry is
  expired after the update so a same-session get_current_revision re-fetches
  from the database.
- Session is owned by the UnitOfWork; no independent commits here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from migration_intake.persistence.models import AnswerInstance, AnswerRevision
from migration_intake.persistence.repositories.intakes import IntakeRepository


class AnswerRepository:
    """Persistence adapter for answer instances and append-only revisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_instance(
        self,
        instance_id: str,
        intake_id: str,
        question_id: str,
        created_at: datetime,
        applicability: str = "APPLICABLE",
        value_state: str = "EMPTY",
        review_state: str = "UNREVIEWED",
    ) -> str:
        """
        Insert an answer instance slot with current_rev_id=NULL.

        The NULL breaks the circular FK with ans_revisions; the pointer is
        updated later via ``advance_current_pointer``.
        """
        IntakeRepository(self._session).lock_content_epoch(intake_id)
        instance = AnswerInstance(
            id=instance_id,
            intake_id=intake_id,
            question_id=question_id,
            created_at=created_at,
            current_rev_id=None,
            applicability=applicability,
            value_state=value_state,
            review_state=review_state,
            updated_at=created_at,
            row_version=1,
        )
        self._session.add(instance)
        self._session.flush()
        return instance_id

    def add_revision(
        self,
        revision_id: str,
        instance_id: str,
        revision_number: int,
        response_json: dict,
        confirm_state: str,
        authored_at: datetime,
        authored_by_id: str,
        response_schema_version: str | None = None,
        raw_boundary_value: str | None = None,
        change_reason: str | None = None,
    ) -> str:
        """
        Insert an append-only revision.

        The UNIQUE(instance_id, revision_number) constraint in the database
        enforces the append-only guarantee; callers should catch
        ``sqlalchemy.exc.IntegrityError`` on duplicate inserts.
        """
        intake_id = self._session.execute(
            select(AnswerInstance.intake_id).where(
                AnswerInstance.id == instance_id
            )
        ).scalar_one_or_none()
        if intake_id is None:
            raise RuntimeError(f"Answer instance {instance_id} not found")
        IntakeRepository(self._session).lock_content_epoch(str(intake_id))
        revision = AnswerRevision(
            id=revision_id,
            instance_id=instance_id,
            revision_number=revision_number,
            response_json=response_json,
            confirm_state=confirm_state,
            authored_at=authored_at,
            authored_by_id=authored_by_id,
            response_schema_version=response_schema_version,
            raw_boundary_value=raw_boundary_value,
            change_reason=change_reason,
        )
        self._session.add(revision)
        self._session.flush()
        return revision_id

    def advance_current_pointer(
        self,
        instance_id: str,
        revision_id: str,
        updated_at: datetime | None = None,
        value_state: str | None = None,
        review_state: str | None = None,
    ) -> None:
        """
        Atomically update ans_instances.current_rev_id and related fields.

        Uses a core UPDATE statement so the write is a single round-trip.
        The matching identity-map entry (if present) is expired after the
        update so any subsequent same-session read re-fetches from the DB.
        """
        values: dict[str, Any] = {
            "current_rev_id": revision_id,
            "row_version": AnswerInstance.row_version + 1,
        }
        if updated_at is not None:
            values["updated_at"] = updated_at
        if value_state is not None:
            values["value_state"] = value_state
        if review_state is not None:
            values["review_state"] = review_state

        stmt = (
            update(AnswerInstance)
            .where(AnswerInstance.id == instance_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        if result.rowcount != 1:
            raise RuntimeError(f"Answer instance {instance_id} not found")
        intake_id = self._session.execute(
            select(AnswerInstance.intake_id).where(AnswerInstance.id == instance_id)
        ).scalar_one()
        IntakeRepository(self._session).bump_content_epoch(str(intake_id))

        # Expire the cached instance (if any) so the next get() reloads.
        # We iterate the identity map rather than calling session.get() to
        # avoid triggering an unintended SELECT.
        for key, obj in list(self._session.identity_map.items()):
            if isinstance(obj, AnswerInstance) and str(obj.id) == str(instance_id):
                self._session.expire(obj)
                break

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_instance(
        self, intake_id: str, question_id: str
    ) -> dict[str, Any] | None:
        """
        Return the answer instance for (intake_id, question_id), or None.

        Returns a plain dict with keys: id, intake_id, question_id,
        created_at, current_rev_id.
        """
        stmt = select(AnswerInstance).where(
            AnswerInstance.intake_id == intake_id,
            AnswerInstance.question_id == question_id,
        )
        instance = self._session.execute(stmt).scalar_one_or_none()
        if instance is None:
            return None
        return {
            "id": str(instance.id),
            "intake_id": str(instance.intake_id),
            "question_id": str(instance.question_id),
            "created_at": instance.created_at,
            "current_rev_id": (
                str(instance.current_rev_id)
                if instance.current_rev_id is not None
                else None
            ),
        }

    def get_current_revision(
        self, instance_id: str
    ) -> dict[str, Any] | None:
        """
        Return the current revision for an answer instance, or None.

        None is returned when:
        - The instance does not exist.
        - The instance exists but current_rev_id is NULL (no revision yet).
        """
        # Always query the DB to avoid stale identity-map reads.
        inst_stmt = select(AnswerInstance).where(
            AnswerInstance.id == instance_id
        )
        instance = self._session.execute(inst_stmt).scalar_one_or_none()
        if instance is None or instance.current_rev_id is None:
            return None

        rev_stmt = select(AnswerRevision).where(
            AnswerRevision.id == instance.current_rev_id
        )
        revision = self._session.execute(rev_stmt).scalar_one_or_none()
        if revision is None:
            return None
        return self._rev_to_dict(revision)

    def get_revisions(self, instance_id: str) -> list[dict[str, Any]]:
        """Return all revisions for an instance in ascending revision_number order."""
        stmt = (
            select(AnswerRevision)
            .where(AnswerRevision.instance_id == instance_id)
            .order_by(AnswerRevision.revision_number)
        )
        revisions = self._session.execute(stmt).scalars().all()
        return [self._rev_to_dict(r) for r in revisions]

    def get_confirmed_answers_for_intake(
        self, intake_id: str
    ) -> list[dict[str, Any]]:
        """
        Return all confirmed answers for an intake with question metadata.

        Returns answers where:
        - The instance has a current revision (current_rev_id is not NULL)
        - The current revision has confirm_state = 'CONFIRMED'

        Each result includes:
        - instance_id, question_id, question_code, section_code, response_type
        - revision_number, response_json, confirm_state, review_state
        - authored_at, authored_by_id, response_schema_version
        """
        from migration_intake.persistence.models import CatalogQuestion, CatalogSection

        # Join instances with their current revisions and question metadata
        stmt = (
            select(
                AnswerInstance,
                AnswerRevision,
                CatalogQuestion.question_code,
                CatalogQuestion.response_type,
                CatalogSection.section_code,
            )
            .join(
                AnswerRevision,
                AnswerInstance.current_rev_id == AnswerRevision.id,
            )
            .join(
                CatalogQuestion,
                AnswerInstance.question_id == CatalogQuestion.id,
            )
            .join(
                CatalogSection,
                CatalogQuestion.section_id == CatalogSection.id,
            )
            .where(
                AnswerInstance.intake_id == intake_id,
                AnswerRevision.confirm_state == "CONFIRMED",
            )
        )

        results = self._session.execute(stmt).all()
        return [
            {
                "instance_id": str(instance.id),
                "question_id": str(instance.question_id),
                "question_code": question_code,
                "section_code": section_code,
                "response_type": response_type,
                "revision_id": str(revision.id),
                "revision_number": revision.revision_number,
                "response_json": revision.response_json,
                "confirm_state": revision.confirm_state,
                "review_state": instance.review_state,
                "authored_at": revision.authored_at,
                "authored_by_id": str(revision.authored_by_id),
                "response_schema_version": revision.response_schema_version,
            }
            for instance, revision, question_code, response_type, section_code in results
        ]

    def get_provenance_references_for_revision(
        self, revision_id: str
    ) -> list[str]:
        """
        Return evidence item IDs linked to a revision.

        Used to build provenance references for canonical snapshots.
        """
        from migration_intake.persistence.models_candidates import AnswerEvidenceLink

        stmt = select(AnswerEvidenceLink.evidence_item_id).where(
            AnswerEvidenceLink.revision_id == revision_id
        )
        results = self._session.execute(stmt).scalars().all()
        return [str(eid) for eid in results]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rev_to_dict(revision: AnswerRevision) -> dict[str, Any]:
        return {
            "id": str(revision.id),
            "instance_id": str(revision.instance_id),
            "revision_number": revision.revision_number,
            "response_json": revision.response_json,
            "confirm_state": revision.confirm_state,
            "authored_at": revision.authored_at,
            "authored_by_id": str(revision.authored_by_id),
            "response_schema_version": revision.response_schema_version,
            "raw_boundary_value": revision.raw_boundary_value,
            "change_reason": revision.change_reason,
        }
