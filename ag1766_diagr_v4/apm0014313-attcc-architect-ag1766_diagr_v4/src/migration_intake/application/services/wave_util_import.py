"""WaveUtil import persistence service (V04b).

Persists a batch of WaveUtil parsed source rows as CANDIDATES for review.

Architecture rules (V04b candidate-first invariant):
- Import creates candidates and findings, never direct canonical rows.
- NEW_ROW, EXACT_MATCH, PROBABLE_MATCH, AMBIGUOUS_MATCH, APPLICATION_MISMATCH
  all become persisted candidate records first.
- Only explicit review actions (accept) create canonical rows.
- One UoW per import_batch call; commit or full rollback.
- Returns only plain dicts and dataclass instances — no ORM entities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.domain.wave_util_matching import (
    CanonicalRow,
    MatchOutcome,
    SourceRow,
    WaveUtilMatcher,
)
from migration_intake.persistence.models import Actor
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.persistence.unit_of_work import uow_context

# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass
class WaveUtilImportRowResult:
    """Outcome record for one source row in an import batch."""

    server_name: str | None
    source_locator: str
    outcome: str                    # MatchOutcome value as string
    candidate_id: str | None = None  # set for all valid outcomes (V04b)
    matched_row_id: str | None = None  # set for EXACT_MATCH, PROBABLE_MATCH, etc.
    findings: list[str] = field(default_factory=list)  # human-readable codes


@dataclass
class WaveUtilImportResult:
    """Aggregate outcome for an entire import batch."""

    total_rows: int
    candidates_created: int      # V04b: all valid rows become candidates
    skipped_rows: int            # INVALID_IDENTITY, DUPLICATE_SOURCE_ROW
    findings_created: int        # findings for warnings/errors
    row_results: list[WaveUtilImportRowResult]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _ensure_actor(session, actor: ActorContext, now: datetime) -> None:
    """
    Insert the actor row if it does not already exist.

    Uses a check-then-insert within the current session transaction.
    The caller must not commit between the check and the insert.
    """
    stmt = select(Actor).where(Actor.id == actor.actor_id)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        actor_row = Actor(
            id=actor.actor_id,
            display_name=actor.display_name or "Unknown",
            attuid=None,
            created_at=now,
        )
        session.add(actor_row)
        session.flush()


def _normalise(server_name: str) -> str:
    """Return the normalised (stripped, lowercased) server name."""
    return server_name.strip().lower()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


# Outcomes that create candidates (V04b: all valid outcomes become candidates)
_CANDIDATE_OUTCOMES: frozenset[MatchOutcome] = frozenset(
    {
        MatchOutcome.NEW_ROW,
        MatchOutcome.EXACT_MATCH,
        MatchOutcome.PROBABLE_MATCH,
        MatchOutcome.AMBIGUOUS_MATCH,
        MatchOutcome.APPLICATION_MISMATCH,
    }
)

# Outcomes that are skipped (no candidate created)
_SKIP_OUTCOMES: frozenset[MatchOutcome] = frozenset(
    {
        MatchOutcome.DUPLICATE_SOURCE_ROW,
        MatchOutcome.INVALID_IDENTITY,
    }
)


class WaveUtilImportService:
    """
    Persists a batch of WaveUtil parsed rows as CANDIDATES (V04b).

    The candidate-first invariant means:
    - All valid outcomes (NEW_ROW, EXACT_MATCH, PROBABLE_MATCH, etc.) create
      candidate records for review.
    - Only explicit accept actions create canonical rows.
    - Invalid outcomes (DUPLICATE_SOURCE_ROW, INVALID_IDENTITY) create findings.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._matcher = WaveUtilMatcher()

    def import_batch(
        self,
        application_id: str,
        intake_id: str,
        evidence_item_id: str,
        import_run_id: str,
        source_rows: list[SourceRow],
        actor: ActorContext,
    ) -> WaveUtilImportResult:
        """
        Match source_rows against canonical state and persist as CANDIDATES.

        V04b candidate-first invariant:
        - NEW_ROW, EXACT_MATCH, PROBABLE_MATCH, AMBIGUOUS_MATCH, APPLICATION_MISMATCH
          → create candidate record for review
        - DUPLICATE_SOURCE_ROW, INVALID_IDENTITY
          → create finding record (skipped)

        All writes are committed atomically at the end of the method.
        """
        now = datetime.now(tz=UTC)

        candidates_created = 0
        skipped_rows = 0
        findings_created = 0
        row_results: list[WaveUtilImportRowResult] = []

        with uow_context(self._session_factory) as uow:
            session = uow._session

            # Ensure the actor exists in the DB (FK requirement).
            _ensure_actor(session, actor, now)

            wave_util_repo = WaveUtilRepository(session)
            candidate_repo = CandidateRepository(session)

            # Load current canonical rows for this application.
            canonical_dicts = wave_util_repo.list_rows_for_application(application_id)
            canonical_rows: list[CanonicalRow] = [
                CanonicalRow(
                    row_id=d["id"],
                    server_name=d["server_name"],
                    application_id=d["application_id"],
                    environment=d["environment"],
                    scope=d["scope"],
                    current_field_values={},
                )
                for d in canonical_dicts
            ]

            # Run the pure-domain batch matcher.
            match_results = self._matcher.match_batch(
                source_rows, canonical_rows, application_id
            )

            for source_row, match_result in zip(source_rows, match_results):
                outcome = match_result.outcome

                if outcome in _CANDIDATE_OUTCOMES:
                    # Create a candidate record for review
                    server_name = source_row.server_name or match_result.server_name

                    # Determine target key based on outcome
                    if outcome == MatchOutcome.NEW_ROW:
                        target_key = f"WAVEUTIL-NEW-{_normalise(server_name or 'unknown')}"
                    else:
                        # For matches, include the matched row ID
                        target_key = f"WAVEUTIL-{match_result.canonical_row_id or 'unknown'}"

                    candidate = candidate_repo.create_candidate(
                        import_run_id=import_run_id,
                        application_id=application_id,
                        intake_id=intake_id,
                        evidence_item_id=evidence_item_id,
                        target_kind="WAVEUTIL_ROW",
                        target_key=target_key,
                        origin="wave_util_import",
                        extractor_version="1.0.0",
                        contract_version="WAVEUTIL_V1",
                        raw_value_json={
                            "server_name": server_name,
                            "environment": source_row.environment,
                            "scope": source_row.scope,
                            "fields": dict(source_row.raw_fields),
                            "match_outcome": outcome.value,
                            "matched_row_id": match_result.canonical_row_id,
                        },
                        source_locator={
                            "locator": match_result.source_locator,
                            "sheet": "WaveUtil",
                        },
                        confidence=self._outcome_to_confidence(outcome),
                    )

                    row_results.append(
                        WaveUtilImportRowResult(
                            server_name=server_name,
                            source_locator=match_result.source_locator,
                            outcome=outcome.value,
                            candidate_id=str(candidate.id),
                            matched_row_id=match_result.canonical_row_id,
                        )
                    )
                    candidates_created += 1

                else:
                    # DUPLICATE_SOURCE_ROW or INVALID_IDENTITY - create finding
                    row_results.append(
                        WaveUtilImportRowResult(
                            server_name=match_result.server_name,
                            source_locator=match_result.source_locator,
                            outcome=outcome.value,
                            findings=[outcome.value],
                        )
                    )
                    skipped_rows += 1
                    findings_created += 1

            uow.commit()

        return WaveUtilImportResult(
            total_rows=len(source_rows),
            candidates_created=candidates_created,
            skipped_rows=skipped_rows,
            findings_created=findings_created,
            row_results=row_results,
        )

    @staticmethod
    def _outcome_to_confidence(outcome: MatchOutcome) -> float | None:
        """Map match outcome to confidence score."""
        confidence_map = {
            MatchOutcome.EXACT_MATCH: 1.0,
            MatchOutcome.NEW_ROW: 0.9,
            MatchOutcome.PROBABLE_MATCH: 0.7,
            MatchOutcome.AMBIGUOUS_MATCH: 0.3,
            MatchOutcome.APPLICATION_MISMATCH: 0.1,
        }
        return confidence_map.get(outcome)
