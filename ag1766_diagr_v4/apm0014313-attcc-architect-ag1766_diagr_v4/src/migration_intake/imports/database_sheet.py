"""
Database extension sheet adapter (B05).

Parses Database legacy-extension rows against the hardcoded mapping table.
Key extra behaviour: detects known DUPLICATE-mapped rows and produces
corroborating evidence, intra-document conflict findings, or duplicate
template structure findings depending on value agreement (section 15.4).

Disposition rules (section 15.4):
- DUPLICATE rows where both values are identical → both locators retained as
  corroborating evidence; no conflict finding.
- DUPLICATE rows with different non-blank values → both retained as candidates
  plus an intra-document DUPLICATE_CONFLICT finding.
- DUPLICATE rows where one is blank → use populated row as candidate and
  raise a DUPLICATE_TEMPLATE finding for the blank row.
- Unknown/questionable source metadata must NOT establish field authority.
- Blank rows (both question and response empty) are silently skipped.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from migration_intake.imports.extension_maps import ExtensionMapping, get_mapping

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DatabaseFindingType(str, Enum):
    """Classification of a Database sheet finding."""

    UNMAPPED = "UNMAPPED"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    DUPLICATE_TEMPLATE = "DUPLICATE_TEMPLATE"
    MISSING_DETAIL = "MISSING_DETAIL"


@dataclass(frozen=True)
class DatabaseCandidate:
    """A valid candidate extracted from a Database sheet row.

    Attributes:
        row_number:            1-based position of the row in the input list.
        disposition:           Mapping disposition (DUPLICATE, etc.).
        target_question_code:  Catalog question code for MAP_TO_QUESTION rows.
        target_register_field: Register field name for MAP_TO_REGISTER_FIELD /
                               DUPLICATE rows.
        raw_question:          Original question string from the sheet.
        raw_response:          Original response string from the sheet.
        source_locator:        "Sheet:Database/Row:{n}" for provenance tracking.
        origin:                Always "DETERMINISTIC" — no AI inference.
    """

    row_number: int
    disposition: str
    target_question_code: str | None
    target_register_field: str | None
    raw_question: str
    raw_response: str
    source_locator: str
    origin: str = "DETERMINISTIC"


@dataclass(frozen=True)
class DatabaseFinding:
    """A finding raised during Database sheet parsing.

    Attributes:
        row_number:        1-based position in the input list.
        finding_type:      Classification of the finding.
        raw_question:      Original question string.
        raw_response:      Original response string.
        suggested_mapping: Suggested target field if a mapping exists.
        detail:            Human-readable explanation.
    """

    row_number: int
    finding_type: DatabaseFindingType
    raw_question: str
    raw_response: str
    suggested_mapping: str | None
    detail: str


@dataclass(frozen=True)
class DatabaseSheetResult:
    """Immutable result of parsing a Database sheet.

    Attributes:
        outcome:            "VALID" — adapter always parses successfully;
                            individual row issues are captured in findings.
        candidates:         Tuple of valid DatabaseCandidate objects.
        findings:           Tuple of DatabaseFinding objects for problem rows.
        blank_rows_skipped: Number of fully-blank rows that were silently dropped.
    """

    outcome: str
    candidates: tuple[DatabaseCandidate, ...]
    findings: tuple[DatabaseFinding, ...]
    blank_rows_skipped: int


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

# Internal type aliases for readability
_OccurrenceList = list[tuple[int, str, str, ExtensionMapping]]


class DatabaseSheetAdapter:
    """Parses Database extension rows against the hardcoded mapping table.

    Input rows are dicts with at minimum the keys ``'question'`` and
    ``'response'``.  Rows where both fields are blank (or whitespace-only)
    are skipped and counted in ``DatabaseSheetResult.blank_rows_skipped``.
    """

    def parse(self, rows: list[dict]) -> DatabaseSheetResult:
        """Parse all rows and return an immutable result.

        Duplicate detection (section 15.4):
        - Rows whose mapping has ``disposition == "DUPLICATE"`` are grouped by
          their normalised question anchor before being processed.
        - All other rows are processed individually.

        Args:
            rows: List of dicts with keys ``'question'`` and ``'response'``.

        Returns:
            DatabaseSheetResult with candidates, findings, and skip counts.
        """
        candidates: list[DatabaseCandidate] = []
        findings: list[DatabaseFinding] = []
        blank_rows_skipped = 0

        # ── First pass: classify each row ─────────────────────────────────
        # Tuple: (row_number, raw_question, raw_response, mapping_or_None, norm_q)
        classified: list[tuple[int, str, str, ExtensionMapping | None, str]] = []

        for i, row in enumerate(rows, 1):
            raw_question: str = row.get("question", "")
            raw_response: str = row.get("response", "")

            # Blank-row guard (both question AND response blank)
            if not raw_question.strip() and not raw_response.strip():
                blank_rows_skipped += 1
                continue

            normalized_q = " ".join(raw_question.split())
            mapping = get_mapping("Database", normalized_q)
            classified.append((i, raw_question, raw_response, mapping, normalized_q))

        # ── Second pass: route into DUPLICATE groups vs individual rows ────
        # Key: normalised question anchor; value: list of occurrences
        duplicate_groups: dict[str, _OccurrenceList] = defaultdict(list)
        non_duplicate_rows: list[tuple[int, str, str, ExtensionMapping | None, str]] = []

        for row_num, raw_q, raw_r, mapping, norm_q in classified:
            if mapping is not None and mapping.disposition == "DUPLICATE":
                duplicate_groups[norm_q].append((row_num, raw_q, raw_r, mapping))
            else:
                non_duplicate_rows.append((row_num, raw_q, raw_r, mapping, norm_q))

        # ── Process individual (non-DUPLICATE) rows ────────────────────────
        for row_num, raw_q, raw_r, mapping, norm_q in non_duplicate_rows:
            locator = f"Sheet:Database/Row:{row_num}"
            if mapping is None:
                findings.append(
                    DatabaseFinding(
                        row_number=row_num,
                        finding_type=DatabaseFindingType.UNMAPPED,
                        raw_question=raw_q,
                        raw_response=raw_r,
                        suggested_mapping=None,
                        detail=(
                            f"No mapping found for '{norm_q}' in Database sheet"
                        ),
                    )
                )
            else:
                # Non-DUPLICATE mapping: produce candidate if response is present
                if raw_r.strip():
                    candidates.append(
                        DatabaseCandidate(
                            row_number=row_num,
                            disposition=mapping.disposition,
                            target_question_code=mapping.target_question_code,
                            target_register_field=mapping.target_register_field,
                            raw_question=raw_q,
                            raw_response=raw_r,
                            source_locator=locator,
                        )
                    )
                else:
                    findings.append(
                        DatabaseFinding(
                            row_number=row_num,
                            finding_type=DatabaseFindingType.MISSING_DETAIL,
                            raw_question=raw_q,
                            raw_response=raw_r,
                            suggested_mapping=(
                                mapping.target_question_code or mapping.target_register_field
                            ),
                            detail=f"Blank response for '{norm_q}'",
                        )
                    )

        # ── Process DUPLICATE groups ───────────────────────────────────────
        for norm_q, occurrences in duplicate_groups.items():
            if len(occurrences) == 1:
                self._process_single_duplicate(
                    occurrences[0], norm_q, candidates, findings
                )
            else:
                self._process_multi_duplicate(
                    occurrences, norm_q, candidates, findings
                )

        return DatabaseSheetResult(
            outcome="VALID",
            candidates=tuple(candidates),
            findings=tuple(findings),
            blank_rows_skipped=blank_rows_skipped,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_candidate(
        row_num: int,
        raw_q: str,
        raw_r: str,
        mapping: ExtensionMapping,
    ) -> DatabaseCandidate:
        return DatabaseCandidate(
            row_number=row_num,
            disposition="DUPLICATE",
            target_question_code=mapping.target_question_code,
            target_register_field=mapping.target_register_field,
            raw_question=raw_q,
            raw_response=raw_r,
            source_locator=f"Sheet:Database/Row:{row_num}",
        )

    @staticmethod
    def _process_single_duplicate(
        occurrence: tuple[int, str, str, ExtensionMapping],
        norm_q: str,
        candidates: list[DatabaseCandidate],
        findings: list[DatabaseFinding],
    ) -> None:
        """Handle a DUPLICATE-mapped question that appears exactly once."""
        row_num, raw_q, raw_r, mapping = occurrence
        if raw_r.strip():
            candidates.append(
                DatabaseSheetAdapter._make_candidate(row_num, raw_q, raw_r, mapping)
            )
        else:
            findings.append(
                DatabaseFinding(
                    row_number=row_num,
                    finding_type=DatabaseFindingType.MISSING_DETAIL,
                    raw_question=raw_q,
                    raw_response=raw_r,
                    suggested_mapping=mapping.target_register_field,
                    detail=f"Blank response for DUPLICATE-mapped '{norm_q}'",
                )
            )

    @staticmethod
    def _process_multi_duplicate(
        occurrences: _OccurrenceList,
        norm_q: str,
        candidates: list[DatabaseCandidate],
        findings: list[DatabaseFinding],
    ) -> None:
        """Handle a DUPLICATE-mapped question that appears two or more times.

        Cases:
        - All blank → MISSING_DETAIL findings for all.
        - Mix of blank and non-blank → non-blank → candidates;
          blank → DUPLICATE_TEMPLATE findings.
        - All non-blank, same value → all → candidates (corroborating).
        - All non-blank, different values → all → candidates +
          one DUPLICATE_CONFLICT finding.
        """
        non_blank = [
            (rn, rq, rr, m) for rn, rq, rr, m in occurrences if rr.strip()
        ]
        blank_ones = [
            (rn, rq, rr, m) for rn, rq, rr, m in occurrences if not rr.strip()
        ]

        if not non_blank:
            # All blank
            for rn, rq, rr, m in blank_ones:
                findings.append(
                    DatabaseFinding(
                        row_number=rn,
                        finding_type=DatabaseFindingType.MISSING_DETAIL,
                        raw_question=rq,
                        raw_response=rr,
                        suggested_mapping=m.target_register_field,
                        detail=f"All occurrences of DUPLICATE-mapped '{norm_q}' are blank",
                    )
                )
            return

        if blank_ones:
            # Mix: populated rows become candidates; blank rows → DUPLICATE_TEMPLATE
            for rn, rq, rr, m in non_blank:
                candidates.append(
                    DatabaseSheetAdapter._make_candidate(rn, rq, rr, m)
                )
            for rn, rq, rr, m in blank_ones:
                findings.append(
                    DatabaseFinding(
                        row_number=rn,
                        finding_type=DatabaseFindingType.DUPLICATE_TEMPLATE,
                        raw_question=rq,
                        raw_response=rr,
                        suggested_mapping=m.target_register_field,
                        detail=(
                            f"Blank duplicate of '{norm_q}' — "
                            f"template structure detected (section 15.4)"
                        ),
                    )
                )
            return

        # All non-blank: compare values (case-insensitive)
        normalised_values = {rr.strip().upper() for _, _, rr, _ in non_blank}

        if len(normalised_values) == 1:
            # Same value → corroborating evidence; retain both locators
            for rn, rq, rr, m in non_blank:
                candidates.append(
                    DatabaseSheetAdapter._make_candidate(rn, rq, rr, m)
                )
        else:
            # Different values → intra-document conflict
            for rn, rq, rr, m in non_blank:
                candidates.append(
                    DatabaseSheetAdapter._make_candidate(rn, rq, rr, m)
                )
            first_row_num, first_raw_q, first_raw_r, _ = non_blank[0]
            values_repr = ", ".join(repr(rr) for _, _, rr, _ in non_blank)
            findings.append(
                DatabaseFinding(
                    row_number=first_row_num,
                    finding_type=DatabaseFindingType.DUPLICATE_CONFLICT,
                    raw_question=first_raw_q,
                    raw_response=first_raw_r,
                    suggested_mapping=None,
                    detail=(
                        f"Intra-document conflict for '{norm_q}': "
                        f"conflicting values [{values_repr}] (section 15.4)"
                    ),
                )
            )
