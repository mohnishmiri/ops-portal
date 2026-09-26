"""
UAQ (Unified Assessment Questionnaire) sheet adapter.

Parses UAQ CSV exports from SharePoint. The UAQ format has columns like:
- Correlation ID, App name, App Acronym
- INV1, INV2, INV3, ... (inventory questions)
- Various assessment fields

This adapter extracts candidates from UAQ data for the intake system.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UAQCandidate:
    """A candidate value extracted from a UAQ row."""

    question_code: str
    raw_value: Any
    source_locator: dict[str, Any]
    confidence: float = 1.0


@dataclass(frozen=True)
class UAQFinding:
    """A finding or issue from UAQ parsing."""

    finding_type: str
    severity: str  # INFO, WARNING, ERROR
    message: str
    row_number: int | None = None
    column: str | None = None


@dataclass
class UAQSheetResult:
    """Result of parsing a UAQ sheet."""

    candidates: list[UAQCandidate] = field(default_factory=list)
    findings: list[UAQFinding] = field(default_factory=list)
    rows_processed: int = 0
    identity: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Column mappings
# ---------------------------------------------------------------------------

# Only reviewed, exact mappings may produce candidates.
UAQ_COLUMN_MAP: dict[str, str] = {
    "INV2-Who is the IT Application Owner": "APP-002",
    "INV3-Who are the primary Technical Contact(s) to work with during the migration?": "APP-002",
    "INV7-Available Environments (Dev/Test/Stage/Prod) that exist to support this workload?": "APP-005",
    "INV9-What is the current operational status of the application?": "APP-003",
    "INV18-What is the App Tier (Mission Critical, Business Critical, …)?": "APP-004",
}

UAQ_IDENTITY_COLUMNS = frozenset({"Correlation ID", "App name", "App Acronym"})


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class UAQSheetAdapter:
    """
    Adapter for parsing UAQ (Unified Assessment Questionnaire) data.
    
    Extracts candidates from UAQ CSV exports.
    """

    def __init__(self) -> None:
        self._column_map = UAQ_COLUMN_MAP

    def parse(self, rows: list[dict[str, Any]]) -> UAQSheetResult:
        """
        Parse UAQ rows and extract candidates.
        
        Args:
            rows: List of row dicts from CSV parsing
            
        Returns:
            UAQSheetResult with candidates and findings
        """
        result = UAQSheetResult()

        if not rows:
            result.findings.append(UAQFinding(
                finding_type="EMPTY_SHEET",
                severity="WARNING",
                message="UAQ sheet contains no data rows",
            ))
            return result

        # Process each row
        for row_idx, row in enumerate(rows, start=2):  # Start at 2 (1-indexed, skip header)
            result.rows_processed += 1

            if row_idx == 2:
                result.identity = {
                    column: row[column]
                    for column in UAQ_IDENTITY_COLUMNS
                    if column in row and row[column] not in (None, "")
                }

            # Extract candidates from known columns
            for col_name, question_code in self._column_map.items():
                if col_name in row:
                    value = row[col_name]

                    # Skip empty values
                    if value is None or (isinstance(value, str) and not value.strip()):
                        continue

                    # Create candidate
                    candidate = UAQCandidate(
                        question_code=question_code,
                        raw_value=value,
                        source_locator={
                            "sheet": "UAQ",
                            "row": row_idx,
                            "column": col_name,
                        },
                        confidence=1.0,
                    )
                    result.candidates.append(candidate)

            # Never guess a target code from an unreviewed source column.
            for col_name, value in row.items():
                if col_name in self._column_map or col_name in UAQ_IDENTITY_COLUMNS:
                    continue
                if value is None or (isinstance(value, str) and not value.strip()):
                    continue
                result.findings.append(UAQFinding(
                    finding_type="UNMAPPED_FIELD",
                    severity="INFO",
                    message="Populated UAQ field has no approved v1 mapping",
                    row_number=row_idx,
                    column=col_name,
                ))

        # Add summary finding
        result.findings.append(UAQFinding(
            finding_type="PARSE_COMPLETE",
            severity="INFO",
            message=f"Parsed {result.rows_processed} rows, extracted {len(result.candidates)} candidates",
        ))

        return result
