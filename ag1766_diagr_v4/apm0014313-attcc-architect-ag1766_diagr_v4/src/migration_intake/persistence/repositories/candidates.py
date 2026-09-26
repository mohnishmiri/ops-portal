"""
Candidate repository (P06).

Provides a collection-like interface for candidate aggregates,
abstracting SQLAlchemy session management.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from migration_intake.persistence.models_candidates import (
    AnswerEvidenceLink,
    Candidate,
    CandidateFinding,
)


class CandidateRepository:
    """
    Repository for candidate persistence operations.

    All methods operate within the provided session and do not
    commit - the caller is responsible for transaction management.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ─────────────────────────────────────────────────────────────────────
    # Candidate operations
    # ─────────────────────────────────────────────────────────────────────

    def add(self, candidate: Candidate) -> None:
        """Add a new candidate to the session."""
        self._session.add(candidate)

    def get_by_id(self, candidate_id: str) -> Candidate | None:
        """Get a candidate by ID."""
        stmt = select(Candidate).where(Candidate.id == candidate_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_intake(
        self,
        intake_id: str,
        state: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Candidate]:
        """
        Get candidates for an intake, optionally filtered by state.

        Returns candidates ordered by created_at ASC.
        """
        stmt = select(Candidate).where(Candidate.intake_id == intake_id)
        if state is not None:
            stmt = stmt.where(Candidate.state == state)
        stmt = stmt.order_by(Candidate.created_at.asc()).limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars().all())

    def get_by_run(self, import_run_id: str) -> list[Candidate]:
        """Get all candidates from an import run."""
        stmt = (
            select(Candidate)
            .where(Candidate.import_run_id == import_run_id)
            .order_by(Candidate.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_by_target(
        self,
        intake_id: str,
        target_kind: str,
        target_key: str,
        state: str | None = None,
    ) -> list[Candidate]:
        """
        Get candidates for a specific target (question, register, etc.).

        Returns candidates ordered by created_at ASC.
        """
        stmt = select(Candidate).where(
            Candidate.intake_id == intake_id,
            Candidate.target_kind == target_kind,
            Candidate.target_key == target_key,
        )
        if state is not None:
            stmt = stmt.where(Candidate.state == state)
        stmt = stmt.order_by(Candidate.created_at.asc())
        return list(self._session.execute(stmt).scalars().all())

    def get_by_evidence(self, evidence_item_id: str) -> list[Candidate]:
        """Get all candidates from an evidence item."""
        stmt = (
            select(Candidate)
            .where(Candidate.evidence_item_id == evidence_item_id)
            .order_by(Candidate.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def count_by_intake(
        self,
        intake_id: str,
        state: str | None = None,
    ) -> int:
        """Count candidates for an intake, optionally filtered by state."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(Candidate).where(
            Candidate.intake_id == intake_id
        )
        if state is not None:
            stmt = stmt.where(Candidate.state == state)
        return self._session.execute(stmt).scalar() or 0

    def count_by_run(self, import_run_id: str) -> int:
        """Count candidates from an import run."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(Candidate).where(
            Candidate.import_run_id == import_run_id
        )
        return self._session.execute(stmt).scalar() or 0

    def update_state(
        self,
        candidate_id: str,
        new_state: str,
        decided_by_id: str,
        decision_rationale: str | None = None,
        accepted_value_json: dict | None = None,
        expected_version: int | None = None,
    ) -> Candidate:
        """
        Update candidate state with decision metadata.

        Raises:
            ValueError: If candidate not found or version mismatch.
        """
        candidate = self.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        if expected_version is not None and candidate.row_version != expected_version:
            raise ValueError(
                f"Version mismatch: expected {expected_version}, got {candidate.row_version}"
            )

        now = datetime.now(tz=UTC)
        candidate.state = new_state
        candidate.decided_by_id = decided_by_id
        candidate.decided_at = now
        candidate.decision_rationale = decision_rationale
        if accepted_value_json is not None:
            candidate.accepted_value_json = accepted_value_json
        candidate.row_version += 1

        return candidate

    def compare_and_set_state(
        self,
        *,
        candidate_id: str,
        expected_row_version: int,
        expected_state: str,
        new_state: str,
        decided_by_id: str,
        decided_at: datetime,
        decision_rationale: str | None = None,
        accepted_value_json: dict | None = None,
    ) -> bool:
        """
        Atomically transition a candidate state using compare-and-set semantics.

        Returns True when one row transitioned; False when the candidate has been
        concurrently modified or is no longer in the expected state.
        """
        values = {
            "state": new_state,
            "decided_by_id": decided_by_id,
            "decided_at": decided_at,
            "decision_rationale": decision_rationale,
            "row_version": Candidate.row_version + 1,
        }
        if accepted_value_json is not None:
            values["accepted_value_json"] = accepted_value_json

        stmt = (
            update(Candidate)
            .where(
                Candidate.id == candidate_id,
                Candidate.row_version == expected_row_version,
                Candidate.state == expected_state,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        return (result.rowcount or 0) == 1

    # ─────────────────────────────────────────────────────────────────────
    # Finding operations
    # ─────────────────────────────────────────────────────────────────────

    def add_finding(self, finding: CandidateFinding) -> None:
        """Add a new finding to the session."""
        self._session.add(finding)

    def get_findings_by_candidate(self, candidate_id: str) -> list[CandidateFinding]:
        """Get all findings for a candidate."""
        stmt = (
            select(CandidateFinding)
            .where(CandidateFinding.candidate_id == candidate_id)
            .order_by(CandidateFinding.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_findings_by_run(self, import_run_id: str) -> list[CandidateFinding]:
        """Get all findings from an import run."""
        stmt = (
            select(CandidateFinding)
            .where(CandidateFinding.import_run_id == import_run_id)
            .order_by(CandidateFinding.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def count_findings_by_run(self, import_run_id: str) -> int:
        """Count findings from an import run."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(CandidateFinding).where(
            CandidateFinding.import_run_id == import_run_id
        )
        return self._session.execute(stmt).scalar() or 0

    # ─────────────────────────────────────────────────────────────────────
    # Evidence link operations
    # ─────────────────────────────────────────────────────────────────────

    def add_evidence_link(self, link: AnswerEvidenceLink) -> None:
        """Add a new evidence link to the session."""
        self._session.add(link)

    def get_evidence_links_by_revision(
        self, revision_id: str
    ) -> list[AnswerEvidenceLink]:
        """Get all evidence links for an answer revision."""
        stmt = (
            select(AnswerEvidenceLink)
            .where(AnswerEvidenceLink.revision_id == revision_id)
            .order_by(AnswerEvidenceLink.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_evidence_links_by_evidence(
        self, evidence_item_id: str
    ) -> list[AnswerEvidenceLink]:
        """Get all evidence links for an evidence item."""
        stmt = (
            select(AnswerEvidenceLink)
            .where(AnswerEvidenceLink.evidence_item_id == evidence_item_id)
            .order_by(AnswerEvidenceLink.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    # ─────────────────────────────────────────────────────────────────────
    # Factory methods
    # ─────────────────────────────────────────────────────────────────────

    def create_candidate(
        self,
        import_run_id: str,
        application_id: str,
        intake_id: str,
        evidence_item_id: str,
        target_kind: str,
        target_key: str,
        origin: str,
        extractor_version: str,
        contract_version: str,
        raw_value_json: dict,
        normalized_value_json: dict | None = None,
        scope_json: dict | None = None,
        source_locator: dict | None = None,
        confidence: float | None = None,
        response_schema_version: str | None = None,
    ) -> Candidate:
        """
        Create a new candidate with required fields.

        The candidate is added to the session but not committed.
        """
        now = datetime.now(tz=UTC)
        candidate = Candidate(
            id=str(uuid.uuid4()),
            import_run_id=import_run_id,
            application_id=application_id,
            intake_id=intake_id,
            evidence_item_id=evidence_item_id,
            target_kind=target_kind,
            target_key=target_key,
            origin=origin,
            extractor_version=extractor_version,
            contract_version=contract_version,
            response_schema_version=response_schema_version,
            source_locator=source_locator,
            raw_value_json=raw_value_json,
            normalized_value_json=normalized_value_json,
            scope_json=scope_json,
            confidence=confidence,
            state="PROPOSED",
            row_version=1,
            created_at=now,
        )
        self.add(candidate)
        return candidate

    def create_finding(
        self,
        import_run_id: str,
        finding_type: str,
        severity: str,
        message: str,
        candidate_id: str | None = None,
        details_json: dict | None = None,
        source_locator: dict | None = None,
    ) -> CandidateFinding:
        """
        Create a new finding with required fields.

        The finding is added to the session but not committed.
        """
        now = datetime.now(tz=UTC)
        finding = CandidateFinding(
            id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            import_run_id=import_run_id,
            finding_type=finding_type,
            severity=severity,
            message=message,
            details_json=details_json,
            source_locator=source_locator,
            created_at=now,
        )
        self.add_finding(finding)
        return finding

    def create_evidence_link(
        self,
        revision_id: str,
        evidence_item_id: str,
        link_type: str,
        candidate_id: str | None = None,
        source_locator: dict | None = None,
    ) -> AnswerEvidenceLink:
        """
        Create a new evidence link with required fields.

        The link is added to the session but not committed.
        """
        now = datetime.now(tz=UTC)
        link = AnswerEvidenceLink(
            id=str(uuid.uuid4()),
            revision_id=revision_id,
            evidence_item_id=evidence_item_id,
            candidate_id=candidate_id,
            link_type=link_type,
            source_locator=source_locator,
            created_at=now,
        )
        self.add_evidence_link(link)
        return link
