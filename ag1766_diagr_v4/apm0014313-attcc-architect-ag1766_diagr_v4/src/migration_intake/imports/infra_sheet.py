"""
Infra extension sheet adapter (B05).

Parses Infra legacy-extension rows against the hardcoded mapping table.
Produces InfraCandidate objects for valid rows and InfraFinding objects
for every deviation — no value is silently dropped or invented.

Disposition rules (section 15.3):
- Populated rows become candidates ONLY when a mapping exists AND the
  response passes validation for that mapping's target type.
- N/A is never blindly accepted; it requires an explicit transformation.
- NO normalises only for a Boolean target (MAP_TO_REGISTER_FIELD).
- Broad/free text is accepted as a candidate without structured parsing here;
  downstream parsers are responsible for missing-detail findings.
- Blank rows (both question and response empty) are silently skipped.
- Absence is NEVER converted into a negative answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from migration_intake.imports.extension_maps import ExtensionMapping, get_mapping

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class InfraFindingType(str, Enum):
    """Classification of an Infra sheet finding."""

    UNMAPPED = "UNMAPPED"
    RETIRED = "RETIRED"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID_VALUE = "INVALID_VALUE"
    MISSING_DETAIL = "MISSING_DETAIL"


@dataclass(frozen=True)
class InfraCandidate:
    """A valid candidate extracted from an Infra sheet row.

    Attributes:
        row_number:            1-based position of the row in the input list.
        disposition:           Mapping disposition (MAP_TO_QUESTION, etc.).
        target_question_code:  Catalog question code for MAP_TO_QUESTION rows.
        target_register_field: Register field name for MAP_TO_REGISTER_FIELD rows.
        raw_question:          Original question string from the sheet.
        raw_response:          Original response string from the sheet.
        source_locator:        "Sheet:Infra/Row:{n}" for provenance tracking.
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
class InfraFinding:
    """A finding raised during Infra sheet parsing.

    Attributes:
        row_number:        1-based position in the input list.
        finding_type:      Classification of the finding.
        raw_question:      Original question string.
        raw_response:      Original response string.
        suggested_mapping: Suggested target code/field if a mapping exists.
        detail:            Human-readable explanation.
    """

    row_number: int
    finding_type: InfraFindingType
    raw_question: str
    raw_response: str
    suggested_mapping: str | None
    detail: str


@dataclass(frozen=True)
class InfraSheetResult:
    """Immutable result of parsing an Infra sheet.

    Attributes:
        outcome:            "VALID" — adapter always parses successfully;
                            individual row issues are captured in findings.
        candidates:         Tuple of valid InfraCandidate objects.
        findings:           Tuple of InfraFinding objects for problem rows.
        blank_rows_skipped: Number of fully-blank rows that were silently dropped.
    """

    outcome: str
    candidates: tuple[InfraCandidate, ...]
    findings: tuple[InfraFinding, ...]
    blank_rows_skipped: int


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class InfraSheetAdapter:
    """Parses Infra extension rows against the hardcoded mapping table.

    Input rows are dicts with at minimum the keys ``'question'`` and
    ``'response'``.  Rows where both fields are blank (or whitespace-only)
    are skipped and counted in ``InfraSheetResult.blank_rows_skipped``.
    """

    def parse(self, rows: list[dict]) -> InfraSheetResult:
        """Parse all rows and return an immutable result.

        Args:
            rows: List of dicts with keys ``'question'`` and ``'response'``.

        Returns:
            InfraSheetResult with candidates, findings, and skip counts.
        """
        candidates: list[InfraCandidate] = []
        findings: list[InfraFinding] = []
        blank_rows_skipped = 0

        for i, row in enumerate(rows, 1):
            raw_question: str = row.get("question", "")
            raw_response: str = row.get("response", "")

            # ── Blank-row guard ───────────────────────────────────────────
            if not raw_question.strip() and not raw_response.strip():
                blank_rows_skipped += 1
                continue

            # ── Normalize question for lookup ─────────────────────────────
            normalized_q = " ".join(raw_question.split())
            source_locator = f"Sheet:Infra/Row:{i}"

            # ── Mapping lookup ────────────────────────────────────────────
            mapping = get_mapping("Infra", normalized_q)

            if mapping is None:
                findings.append(
                    InfraFinding(
                        row_number=i,
                        finding_type=InfraFindingType.UNMAPPED,
                        raw_question=raw_question,
                        raw_response=raw_response,
                        suggested_mapping=None,
                        detail=(
                            f"No mapping found for '{normalized_q}' in Infra sheet"
                        ),
                    )
                )
                continue

            # ── RETIRED disposition ───────────────────────────────────────
            if mapping.disposition == "RETIRED":
                findings.append(
                    InfraFinding(
                        row_number=i,
                        finding_type=InfraFindingType.RETIRED,
                        raw_question=raw_question,
                        raw_response=raw_response,
                        suggested_mapping=None,
                        detail=(
                            f"Question '{normalized_q}' is retired "
                            f"(legacy_number={mapping.legacy_number}): {mapping.notes}"
                        ),
                    )
                )
                continue

            # ── Response validation ───────────────────────────────────────
            finding_type = self._validate_response(raw_response, mapping)
            if finding_type is not None:
                findings.append(
                    InfraFinding(
                        row_number=i,
                        finding_type=finding_type,
                        raw_question=raw_question,
                        raw_response=raw_response,
                        suggested_mapping=(
                            mapping.target_question_code or mapping.target_register_field
                        ),
                        detail=self._finding_detail(finding_type, raw_response, mapping),
                    )
                )
                continue

            # ── Produce candidate ─────────────────────────────────────────
            candidates.append(
                InfraCandidate(
                    row_number=i,
                    disposition=mapping.disposition,
                    target_question_code=mapping.target_question_code,
                    target_register_field=mapping.target_register_field,
                    raw_question=raw_question,
                    raw_response=raw_response,
                    source_locator=source_locator,
                )
            )

        return InfraSheetResult(
            outcome="VALID",
            candidates=tuple(candidates),
            findings=tuple(findings),
            blank_rows_skipped=blank_rows_skipped,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_response(
        raw_response: str, mapping: ExtensionMapping
    ) -> InfraFindingType | None:
        """Validate the response value against the mapping's target type.

        Returns:
            The appropriate InfraFindingType if the response is invalid,
            or None if the response is acceptable (candidate should be created).
        """
        stripped = raw_response.strip()

        # Blank response — canonical control may require this info
        if not stripped:
            return InfraFindingType.MISSING_DETAIL

        upper = stripped.upper()

        # N/A — only accepted when the mapping provides an explicit transformation
        if upper == "N/A":
            if (
                mapping.transformation
                and "NA" in mapping.transformation.upper()
            ):
                return None
            return InfraFindingType.INVALID_VALUE

        # NO — only normalizes for a Boolean target (MAP_TO_REGISTER_FIELD)
        if upper == "NO":
            if mapping.disposition == "MAP_TO_REGISTER_FIELD":
                return None  # boolean register field accepts NO
            return InfraFindingType.INVALID_VALUE

        # All other non-blank values are accepted for candidate creation
        return None

    @staticmethod
    def _finding_detail(
        finding_type: InfraFindingType,
        raw_response: str,
        mapping: ExtensionMapping,
    ) -> str:
        """Produce a human-readable detail string for a response finding."""
        upper = raw_response.strip().upper()

        if finding_type == InfraFindingType.INVALID_VALUE:
            if upper == "N/A":
                return (
                    f"Response 'N/A' not accepted for "
                    f"'{mapping.normalized_question_anchor}': "
                    f"no explicit applicability mapping defined (section 15.3)"
                )
            if upper == "NO":
                target = (
                    mapping.target_question_code
                    or mapping.target_register_field
                    or "unknown target"
                )
                return (
                    f"Response 'NO' not accepted for "
                    f"'{mapping.normalized_question_anchor}': "
                    f"target '{target}' is not a Boolean type (section 15.3)"
                )
            return (
                f"Response '{raw_response}' is invalid for "
                f"'{mapping.normalized_question_anchor}'"
            )

        if finding_type == InfraFindingType.MISSING_DETAIL:
            return (
                f"Blank response for '{mapping.normalized_question_anchor}' — "
                f"canonical control may require this value (section 15.3)"
            )

        return f"Finding {finding_type} for '{mapping.normalized_question_anchor}'"
