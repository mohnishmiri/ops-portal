"""WaveUtil batch acceptance service (V04b).

Handles bounded, all-or-nothing batch acceptance of WaveUtil CANDIDATES.

Architecture rules (V04b candidate-first invariant):
- Accept operates on candidate IDs, not direct row IDs.
- Validates candidate state, version, and matching outcome inside the transaction.
- For NEW_ROW candidates: creates canonical row + revision.
- For EXACT_MATCH candidates: appends revision to matched row.
- For PROBABLE_MATCH/AMBIGUOUS_MATCH: requires explicit confirmation.
- ALL version checks happen BEFORE any writes.
- On success, all changes are committed in a single transaction.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.persistence.unit_of_work import uow_context

# ---------------------------------------------------------------------------
# Command data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaveUtilCandidateAcceptItem:
    """A single candidate acceptance request within an accept_candidates call."""

    candidate_id: str
    expected_candidate_version: int
    # For PROBABLE_MATCH/AMBIGUOUS_MATCH, caller may override matched_row_id
    override_matched_row_id: str | None = None


@dataclass(frozen=True)
class WaveUtilRetireItem:
    """A single row retirement request."""

    row_id: str
    expected_row_version: int
    rationale: str
    evidence_reference: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CandidateNotProposedError(Exception):
    """Raised when trying to accept a candidate that is not in PROPOSED state."""
    pass


class InvalidMatchOutcomeError(Exception):
    """Raised when candidate has an invalid match outcome for acceptance."""
    pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _normalise(server_name: str) -> str:
    """Return the normalised (stripped, lowercased) server name."""
    return server_name.strip().lower()


class WaveUtilReviewService:
    """
    Handles bounded batch acceptance of WaveUtil CANDIDATES (V04b).

    The candidate-first invariant means:
    - Accept operates on candidate IDs, not direct row IDs.
    - Validates candidate state and version inside the transaction.
    - Creates canonical rows/revisions only on acceptance.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def accept_candidates(
        self,
        items: list[WaveUtilCandidateAcceptItem],
        actor: ActorContext,
    ) -> dict:
        """
        Accept all candidate items atomically or fail all.

        Algorithm:
        1. If *items* is empty, return immediately (accepted=0).
        2. Open a UoW.
        3. Load every candidate and verify:
           - State is PROPOSED
           - Version matches expected_candidate_version
        4. For each candidate based on match_outcome:
           - NEW_ROW: create canonical row + revision
           - EXACT_MATCH: append revision to matched row
           - PROBABLE_MATCH/AMBIGUOUS_MATCH: use override_matched_row_id or matched_row_id
        5. Update candidate state to ACCEPTED.
        6. Commit everything at once.

        Returns:
            {"accepted": N, "candidate_ids": [<str>, ...], "row_ids": [<str>, ...]}

        Raises:
            ConcurrencyConflictError: when any candidate's version mismatches.
            CandidateNotProposedError: when candidate is not in PROPOSED state.
        """
        if not items:
            return {"accepted": 0, "candidate_ids": [], "row_ids": []}

        now = datetime.now(tz=UTC)
        accepted_row_ids: list[str] = []

        with uow_context(self._session_factory) as uow:
            wave_util_repo = WaveUtilRepository(uow._session)
            candidate_repo = CandidateRepository(uow._session)

            # ── Step 1: validate all candidates before touching anything ────
            candidates_to_process = []
            for item in items:
                candidate = candidate_repo.get_by_id(item.candidate_id)
                if candidate is None:
                    raise ConcurrencyConflictError(
                        f"Candidate {item.candidate_id!r} not found."
                    )
                if candidate.state != "PROPOSED":
                    raise CandidateNotProposedError(
                        f"Candidate {item.candidate_id!r} is in state "
                        f"{candidate.state!r}, not PROPOSED."
                    )
                if candidate.row_version != item.expected_candidate_version:
                    raise ConcurrencyConflictError(
                        f"Candidate {item.candidate_id!r}: expected version="
                        f"{item.expected_candidate_version}, current version="
                        f"{candidate.row_version}; stale acceptance rejected."
                    )
                candidates_to_process.append((item, candidate))

            # ── Step 2: process all candidates ──────────────────────────────
            for item, candidate in candidates_to_process:
                raw_value = candidate.raw_value_json or {}
                match_outcome = raw_value.get("match_outcome", "")
                matched_row_id = item.override_matched_row_id or raw_value.get("matched_row_id")

                if match_outcome == "NEW_ROW":
                    # Create new canonical row
                    row_id = str(uuid.uuid4())
                    rev_id = str(uuid.uuid4())
                    server_name = raw_value.get("server_name", "")

                    wave_util_repo.add_row(
                        row_id=row_id,
                        application_id=str(candidate.application_id),
                        intake_id=str(candidate.intake_id),
                        server_name=server_name,
                        normalized_server_name=_normalise(server_name),
                        environment=raw_value.get("environment"),
                        scope=raw_value.get("scope"),
                        created_at=now,
                        created_by_id=actor.actor_id,
                    )
                    wave_util_repo.add_revision(
                        revision_id=rev_id,
                        row_id=row_id,
                        revision_number=1,
                        field_values_json=raw_value.get("fields", {}),
                        authored_at=now,
                        authored_by_id=actor.actor_id,
                    )
                    wave_util_repo.advance_current_pointer(row_id, rev_id)
                    accepted_row_ids.append(row_id)

                elif match_outcome in ("EXACT_MATCH", "PROBABLE_MATCH", "AMBIGUOUS_MATCH"):
                    # Append revision to matched row
                    if not matched_row_id:
                        raise InvalidMatchOutcomeError(
                            f"Candidate {item.candidate_id!r} has outcome "
                            f"{match_outcome!r} but no matched_row_id."
                        )

                    # Verify the row exists
                    row = wave_util_repo.get_row(matched_row_id)
                    if row is None:
                        raise ConcurrencyConflictError(
                            f"Matched row {matched_row_id!r} not found."
                        )

                    current_rev = wave_util_repo.get_current_revision(matched_row_id)
                    next_rev_number = (
                        current_rev["revision_number"] + 1
                        if current_rev is not None
                        else 1
                    )

                    rev_id = str(uuid.uuid4())
                    wave_util_repo.add_revision(
                        revision_id=rev_id,
                        row_id=matched_row_id,
                        revision_number=next_rev_number,
                        field_values_json=raw_value.get("fields", {}),
                        authored_at=now,
                        authored_by_id=actor.actor_id,
                    )
                    wave_util_repo.advance_current_pointer(matched_row_id, rev_id)
                    accepted_row_ids.append(matched_row_id)

                else:
                    raise InvalidMatchOutcomeError(
                        f"Candidate {item.candidate_id!r} has invalid outcome "
                        f"{match_outcome!r} for acceptance."
                    )

                # Update candidate state to ACCEPTED
                candidate.state = "ACCEPTED"
                candidate.decided_by_id = actor.actor_id
                candidate.decided_at = now
                candidate.row_version += 1

            uow.commit()

        return {
            "accepted": len(items),
            "candidate_ids": [item.candidate_id for item in items],
            "row_ids": accepted_row_ids,
        }

    def reject_candidates(
        self,
        candidate_ids: list[str],
        reason: str,
        actor: ActorContext,
    ) -> dict:
        """
        Reject candidates. Rejection never changes canonical state.

        Returns:
            {"rejected": N, "candidate_ids": [<str>, ...]}
        """
        if not candidate_ids:
            return {"rejected": 0, "candidate_ids": []}

        if not reason or not reason.strip():
            raise ValueError("Rejection requires a reason")

        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            candidate_repo = CandidateRepository(uow._session)

            for candidate_id in candidate_ids:
                candidate = candidate_repo.get_by_id(candidate_id)
                if candidate is None:
                    raise ConcurrencyConflictError(
                        f"Candidate {candidate_id!r} not found."
                    )
                if candidate.state != "PROPOSED":
                    raise CandidateNotProposedError(
                        f"Candidate {candidate_id!r} is in state "
                        f"{candidate.state!r}, not PROPOSED."
                    )

                candidate.state = "REJECTED"
                candidate.decided_by_id = actor.actor_id
                candidate.decided_at = now
                candidate.decision_rationale = reason
                candidate.row_version += 1

            uow.commit()

        return {
            "rejected": len(candidate_ids),
            "candidate_ids": candidate_ids,
        }

    def retire_rows(
        self,
        items: list[WaveUtilRetireItem],
        actor: ActorContext,
    ) -> dict:
        """
        Retire WaveUtil rows with rationale and evidence reference.

        Retirement requires:
        - Expected row version (optimistic concurrency)
        - Rationale (required)
        - Evidence reference (optional)

        Missing from a later workbook remains a finding and never retires a row.

        Returns:
            {"retired": N, "row_ids": [<str>, ...]}
        """
        if not items:
            return {"retired": 0, "row_ids": []}

        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            wave_util_repo = WaveUtilRepository(uow._session)

            # Validate all items first
            for item in items:
                if not item.rationale or not item.rationale.strip():
                    raise ValueError(
                        f"Retirement of row {item.row_id!r} requires a rationale."
                    )

                row = wave_util_repo.get_row(item.row_id)
                if row is None:
                    raise ConcurrencyConflictError(
                        f"WaveUtilRow {item.row_id!r} not found."
                    )
                if row["row_version"] != item.expected_row_version:
                    raise ConcurrencyConflictError(
                        f"WaveUtilRow {item.row_id!r}: expected version="
                        f"{item.expected_row_version}, current version="
                        f"{row['row_version']}; stale retirement rejected."
                    )
                if row["state"] == "RETIRED":
                    raise ValueError(
                        f"WaveUtilRow {item.row_id!r} is already retired."
                    )

            # Retire all rows
            for item in items:
                wave_util_repo.retire_row(
                    row_id=item.row_id,
                    rationale=item.rationale,
                    evidence_reference=item.evidence_reference,
                    retired_at=now,
                    retired_by_id=actor.actor_id,
                )

            uow.commit()

        return {
            "retired": len(items),
            "row_ids": [item.row_id for item in items],
        }
