"""
WaveUtil Matching and Reconciliation (V03).

Implements pure domain matching and reconciliation logic for WaveUtil rows,
following the rules in section 19 of the architecture design document.

Key rules:
- INVALID_IDENTITY:      server_name blank/None.
- DUPLICATE_SOURCE_ROW:  two rows in the same batch share a normalised server_name.
- EXACT_MATCH:           single canonical row with matching server_name + environment + scope.
- PROBABLE_MATCH:        server_name matches but environment or scope differs.
- AMBIGUOUS_MATCH:       multiple canonical rows share the same server_name (canonical side).
- APPLICATION_MISMATCH:  canonical exists for server but belongs to a different application_id.
- NEW_ROW:               no canonical row found for this server_name.

Reconciliation rules (section 19.3 / 19.6):
- Blank candidate value never clears a canonical answer (BLANK_CANDIDATE finding).
- Different scope is a SCOPE_MISMATCH finding, not a conflict.
- Canonical row absent from new source → MISSING_FROM_SOURCE finding (NOT retirement).

No SQLAlchemy or Pydantic dependencies in the domain layer.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MatchOutcome(str, Enum):
    """All possible outcomes for matching a source row against canonical rows."""

    EXACT_MATCH = "EXACT_MATCH"
    """Single unambiguous match on all identity fields."""

    PROBABLE_MATCH = "PROBABLE_MATCH"
    """Server name matches but secondary fields (environment/scope) differ."""

    NEW_ROW = "NEW_ROW"
    """No candidate matches the server name."""

    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    """Multiple canonical rows could match — no automatic update."""

    APPLICATION_MISMATCH = "APPLICATION_MISMATCH"
    """Row belongs to a different application_id than the current command."""

    DUPLICATE_SOURCE_ROW = "DUPLICATE_SOURCE_ROW"
    """Exact duplicate in the source import batch (same normalised server_name)."""

    INVALID_IDENTITY = "INVALID_IDENTITY"
    """Missing or blank server_name; row cannot be matched."""


class ReconciliationFindingType(str, Enum):
    """Types of reconciliation findings produced by WaveUtilMatcher."""

    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    """Source and canonical rows have different environment/scope values."""

    MISSING_FROM_SOURCE = "MISSING_FROM_SOURCE"
    """A canonical row is not present in the new import batch.
    This is NOT retirement — an explicit retire command is required."""

    FIELD_DISCREPANCY = "FIELD_DISCREPANCY"
    """A specific field value differs between source and canonical."""

    BLANK_CANDIDATE = "BLANK_CANDIDATE"
    """The candidate (source) value for a field is blank — ignored, not applied."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRow:
    """A row from the current import batch (WaveUtil sheet).

    Attributes
    ----------
    server_name:
        Raw server name from the source sheet (may be None or blank).
    environment:
        Normalised environment string from ApplicationEnvironment.normalize()
        (e.g. "PRODUCTION", "TEST", "DEVELOPMENT").  None when absent.
    scope:
        Scope label (e.g. "PROD", "DEV", "TEST").  None when absent.
    source_locator:
        Row location string, e.g. "Sheet:WaveUtil/Row:N".
    raw_fields:
        Arbitrary raw field dict from the sheet row (field_name → raw value).
    """

    server_name: str | None
    environment: str | None
    scope: str | None
    source_locator: str
    raw_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalRow:
    """An existing persisted WaveUtil row.

    Attributes
    ----------
    row_id:
        Internal UUID / stable identifier for the canonical row.
    server_name:
        Canonical server name.
    application_id:
        The application this canonical row is associated with.
    environment:
        Canonical environment code (e.g. "PRODUCTION").  None when absent.
    scope:
        Canonical scope label (e.g. "PROD").  None when absent.
    current_field_values:
        Current approved field values keyed by field name.
    """

    row_id: str
    server_name: str
    application_id: str
    environment: str | None
    scope: str | None
    current_field_values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchResult:
    """The outcome of matching one source row against the canonical register.

    Attributes
    ----------
    source_locator:
        Identifies the source row (e.g. "Sheet:WaveUtil/Row:2").
    server_name:
        The server_name from the source row (may be None for INVALID_IDENTITY).
    outcome:
        The :class:`MatchOutcome` for this row.
    canonical_row_id:
        The matched canonical row ID; None for NEW_ROW / INVALID_IDENTITY /
        AMBIGUOUS_MATCH / DUPLICATE_SOURCE_ROW.
    candidate_row_id:
        For DUPLICATE_SOURCE_ROW, the source_locator of the *other* duplicate;
        otherwise None.
    """

    source_locator: str
    server_name: str | None
    outcome: MatchOutcome
    canonical_row_id: str | None = None
    candidate_row_id: str | None = None


@dataclass(frozen=True)
class ReconciliationFinding:
    """A single reconciliation finding produced during field-level comparison.

    Attributes
    ----------
    finding_type:
        The type of finding.
    server_name:
        The server this finding relates to.
    field_name:
        The specific field involved (empty string when not field-specific).
    detail:
        Human-readable detail string.
    """

    finding_type: ReconciliationFindingType
    server_name: str
    field_name: str = ""
    detail: str = ""


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------


def _normalise_server_name(name: str) -> str:
    """Return a normalised (lowercase, stripped) server name for comparison."""
    return name.strip().lower()


def _is_blank(value: str | None) -> bool:
    """Return True when a value is None or whitespace-only."""
    return value is None or not value.strip()


# ---------------------------------------------------------------------------
# Domain service
# ---------------------------------------------------------------------------


class WaveUtilMatcher:
    """Pure domain service: matches source rows against canonical rows.

    All methods are stateless; no database or external dependencies.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match_batch(
        self,
        source_rows: list[SourceRow],
        canonical_rows: list[CanonicalRow],
        application_id: str,
    ) -> list[MatchResult]:
        """Match a batch of source rows against canonical rows.

        Returns one :class:`MatchResult` per source row, in the same order as
        *source_rows*.

        Parameters
        ----------
        source_rows:
            Rows from the current import batch.
        canonical_rows:
            All existing canonical rows for the application.
        application_id:
            The application being imported (used for APPLICATION_MISMATCH detection).

        Returns
        -------
        list[MatchResult]
            One result per source row.
        """
        # Step 1 — Detect INVALID_IDENTITY rows (blank/None server_name).
        # Step 2 — Detect DUPLICATE_SOURCE_ROW within the valid rows.
        # Step 3 — Match remaining rows against canonical.

        # Build normalised-name → [index] map for duplicate detection.
        name_to_indices: dict[str, list[int]] = defaultdict(list)
        for idx, row in enumerate(source_rows):
            if not _is_blank(row.server_name):
                key = _normalise_server_name(row.server_name)  # type: ignore[arg-type]
                name_to_indices[key].append(idx)

        # Build normalised canonical lookup: norm_name → [CanonicalRow]
        canonical_by_name: dict[str, list[CanonicalRow]] = defaultdict(list)
        for crow in canonical_rows:
            key = _normalise_server_name(crow.server_name)
            canonical_by_name[key].append(crow)

        results: list[MatchResult | None] = [None] * len(source_rows)

        for idx, row in enumerate(source_rows):
            # --- INVALID_IDENTITY ---
            if _is_blank(row.server_name):
                results[idx] = MatchResult(
                    source_locator=row.source_locator,
                    server_name=row.server_name,
                    outcome=MatchOutcome.INVALID_IDENTITY,
                )
                continue

            norm = _normalise_server_name(row.server_name)  # type: ignore[arg-type]

            # --- DUPLICATE_SOURCE_ROW ---
            if len(name_to_indices[norm]) > 1:
                # Find the *other* locator for candidate_row_id
                other_locator = next(
                    source_rows[other_idx].source_locator
                    for other_idx in name_to_indices[norm]
                    if other_idx != idx
                )
                results[idx] = MatchResult(
                    source_locator=row.source_locator,
                    server_name=row.server_name,
                    outcome=MatchOutcome.DUPLICATE_SOURCE_ROW,
                    candidate_row_id=other_locator,
                )
                continue

            # --- Look up canonical candidates ---
            candidates = canonical_by_name.get(norm, [])

            if not candidates:
                # NEW_ROW
                results[idx] = MatchResult(
                    source_locator=row.source_locator,
                    server_name=row.server_name,
                    outcome=MatchOutcome.NEW_ROW,
                )
                continue

            # --- APPLICATION_MISMATCH (all candidates belong to wrong app) ---
            same_app = [c for c in candidates if c.application_id == application_id]
            if not same_app:
                results[idx] = MatchResult(
                    source_locator=row.source_locator,
                    server_name=row.server_name,
                    outcome=MatchOutcome.APPLICATION_MISMATCH,
                )
                continue

            # --- AMBIGUOUS_MATCH (multiple canonical rows for same app/server) ---
            if len(same_app) > 1:
                results[idx] = MatchResult(
                    source_locator=row.source_locator,
                    server_name=row.server_name,
                    outcome=MatchOutcome.AMBIGUOUS_MATCH,
                )
                continue

            # --- Single same-app canonical candidate: EXACT_MATCH or PROBABLE_MATCH ---
            canonical = same_app[0]
            outcome = self._score_single_candidate(row, canonical)
            results[idx] = MatchResult(
                source_locator=row.source_locator,
                server_name=row.server_name,
                outcome=outcome,
                canonical_row_id=canonical.row_id if outcome == MatchOutcome.EXACT_MATCH else None,
            )

        return results  # type: ignore[return-value]

    def find_missing_from_source(
        self,
        source_rows: list[SourceRow],
        canonical_rows: list[CanonicalRow],
    ) -> list[ReconciliationFinding]:
        """Find canonical rows not present in the new source batch.

        Absence of a canonical row from a new import is **not** retirement —
        it produces a MISSING_FROM_SOURCE finding only.  An explicit retire
        command is required to remove a canonical row.

        Parameters
        ----------
        source_rows:
            Rows from the current import batch.
        canonical_rows:
            All existing canonical rows.

        Returns
        -------
        list[ReconciliationFinding]
            MISSING_FROM_SOURCE findings for each canonical row absent from
            *source_rows*.
        """
        source_names: set[str] = {
            _normalise_server_name(r.server_name)  # type: ignore[arg-type]
            for r in source_rows
            if not _is_blank(r.server_name)
        }

        findings: list[ReconciliationFinding] = []
        for crow in canonical_rows:
            norm = _normalise_server_name(crow.server_name)
            if norm not in source_names:
                findings.append(
                    ReconciliationFinding(
                        finding_type=ReconciliationFindingType.MISSING_FROM_SOURCE,
                        server_name=crow.server_name,
                        field_name="",
                        detail=(
                            f"Canonical row {crow.row_id!r} for server "
                            f"{crow.server_name!r} is not present in the new "
                            f"import batch. This is not retirement; an explicit "
                            f"retire command is required."
                        ),
                    )
                )
        return findings

    def reconcile_fields(
        self,
        source_row: SourceRow,
        canonical: CanonicalRow,
        application_id: str,
    ) -> list[ReconciliationFinding]:
        """Perform field-level reconciliation between a source row and a canonical row.

        Rules (section 19.3):
        - Blank candidate value → BLANK_CANDIDATE finding (never clears canonical).
        - Different scope/environment → SCOPE_MISMATCH finding.
        - Different non-blank field value → FIELD_DISCREPANCY finding.

        Parameters
        ----------
        source_row:
            The source import row.
        canonical:
            The matching canonical row.
        application_id:
            Current application context (unused in field reconciliation but
            included for API consistency).

        Returns
        -------
        list[ReconciliationFinding]
            All findings from field comparison.  Empty list means no differences.
        """
        findings: list[ReconciliationFinding] = []
        server_name = source_row.server_name or canonical.server_name

        # --- Scope / environment comparison ---
        # Rule: blank candidate scope → BLANK_CANDIDATE only (never SCOPE_MISMATCH)
        if _is_blank(source_row.scope) and not _is_blank(canonical.scope):
            findings.append(
                ReconciliationFinding(
                    finding_type=ReconciliationFindingType.BLANK_CANDIDATE,
                    server_name=server_name,
                    field_name="scope",
                    detail=(
                        f"Source scope is blank; canonical scope "
                        f"{canonical.scope!r} is preserved."
                    ),
                )
            )
        elif (
            not _is_blank(source_row.scope)
            and not _is_blank(canonical.scope)
            and (source_row.scope or "").strip() != (canonical.scope or "").strip()
        ):
            findings.append(
                ReconciliationFinding(
                    finding_type=ReconciliationFindingType.SCOPE_MISMATCH,
                    server_name=server_name,
                    field_name="scope",
                    detail=(
                        f"Source scope {source_row.scope!r} differs from "
                        f"canonical scope {canonical.scope!r}."
                    ),
                )
            )

        if _is_blank(source_row.environment) and not _is_blank(canonical.environment):
            findings.append(
                ReconciliationFinding(
                    finding_type=ReconciliationFindingType.BLANK_CANDIDATE,
                    server_name=server_name,
                    field_name="environment",
                    detail=(
                        f"Source environment is blank; canonical environment "
                        f"{canonical.environment!r} is preserved."
                    ),
                )
            )
        elif (
            not _is_blank(source_row.environment)
            and not _is_blank(canonical.environment)
            and (source_row.environment or "").strip() != (canonical.environment or "").strip()
        ):
            findings.append(
                ReconciliationFinding(
                    finding_type=ReconciliationFindingType.SCOPE_MISMATCH,
                    server_name=server_name,
                    field_name="environment",
                    detail=(
                        f"Source environment {source_row.environment!r} differs "
                        f"from canonical environment {canonical.environment!r}."
                    ),
                )
            )

        # --- Raw field comparison ---
        for field_name, source_value in source_row.raw_fields.items():
            canonical_value = canonical.current_field_values.get(field_name)

            if _is_blank(source_value):
                if not _is_blank(canonical_value):
                    findings.append(
                        ReconciliationFinding(
                            finding_type=ReconciliationFindingType.BLANK_CANDIDATE,
                            server_name=server_name,
                            field_name=field_name,
                            detail=(
                                f"Source value for {field_name!r} is blank; "
                                f"canonical value {canonical_value!r} is preserved."
                            ),
                        )
                    )
                continue

            # Both non-blank — compare normalised
            if canonical_value is not None and source_value.strip() != canonical_value.strip():
                findings.append(
                    ReconciliationFinding(
                        finding_type=ReconciliationFindingType.FIELD_DISCREPANCY,
                        server_name=server_name,
                        field_name=field_name,
                        detail=(
                            f"Source value {source_value!r} differs from "
                            f"canonical value {canonical_value!r}."
                        ),
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_single_candidate(
        row: SourceRow,
        canonical: CanonicalRow,
    ) -> MatchOutcome:
        """Determine EXACT_MATCH or PROBABLE_MATCH for a single same-app candidate.

        Rules:
        - If either side has a blank environment/scope, treat as matching (no penalty).
        - If both sides have values and they match → EXACT_MATCH.
        - If either environment or scope differs (both non-blank) → PROBABLE_MATCH.
        """
        env_matches = (
            _is_blank(row.environment)
            or _is_blank(canonical.environment)
            or (row.environment or "").strip() == (canonical.environment or "").strip()
        )
        scope_matches = (
            _is_blank(row.scope)
            or _is_blank(canonical.scope)
            or (row.scope or "").strip() == (canonical.scope or "").strip()
        )

        if env_matches and scope_matches:
            return MatchOutcome.EXACT_MATCH
        return MatchOutcome.PROBABLE_MATCH
