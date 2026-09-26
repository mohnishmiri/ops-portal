"""
Workbook contract definitions and sheet-role registry.

The APP_DATA_CAPTURE_V1 contract identifies a workbook by its required
sheet set, exact names (or approved aliases), and header-signature
compatibility with catalog v0.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SheetRole(str, Enum):
    """Functional role assigned to each worksheet in the contract."""

    QUESTIONNAIRE_PROJECTION = "QUESTIONNAIRE_PROJECTION"
    SOURCE_CAPTURE = "SOURCE_CAPTURE"
    REGISTER_DATA = "REGISTER_DATA"
    LEGACY_EXTENSION = "LEGACY_EXTENSION"
    REFERENCE_DATA = "REFERENCE_DATA"


@dataclass(frozen=True)
class SheetContract:
    """
    Contract for a single worksheet within a workbook.

    Attributes:
        canonical_name: The authoritative sheet name expected in the workbook.
        role:           Functional role of the sheet.
        aliases:        Approved alternate spellings for the sheet name.
        required:       If True, absence of this sheet makes the workbook INVALID.
    """

    canonical_name: str
    role: SheetRole
    aliases: frozenset[str] = field(default_factory=frozenset)
    required: bool = True


@dataclass(frozen=True)
class WorkbookContract:
    """
    Full contract definition for a workbook format version.

    Attributes:
        contract_version: Unique string identifying the contract (e.g. 'APP_DATA_CAPTURE_V1').
        sheets:           Ordered tuple of sheet contracts.
    """

    contract_version: str
    sheets: tuple[SheetContract, ...]


# ---------------------------------------------------------------------------
# APP_DATA_CAPTURE_V1 — the canonical intake workbook contract
# ---------------------------------------------------------------------------

APP_DATA_CAPTURE_V1: WorkbookContract = WorkbookContract(
    contract_version="APP_DATA_CAPTURE_V1",
    sheets=(
        SheetContract(
            "App", SheetRole.QUESTIONNAIRE_PROJECTION, frozenset(), required=True
        ),
        SheetContract(
            "iTAP", SheetRole.SOURCE_CAPTURE, frozenset(), required=True
        ),
        SheetContract(
            "Interface", SheetRole.REGISTER_DATA, frozenset(), required=False
        ),
        SheetContract(
            "WaveUtil", SheetRole.REGISTER_DATA, frozenset(), required=True
        ),
        SheetContract(
            "Infra", SheetRole.LEGACY_EXTENSION, frozenset(), required=True
        ),
        SheetContract(
            "Database", SheetRole.LEGACY_EXTENSION, frozenset(), required=True
        ),
        SheetContract(
            "TSS", SheetRole.REGISTER_DATA, frozenset(), required=True
        ),
        SheetContract(
            "Provisioning", SheetRole.REFERENCE_DATA, frozenset(), required=True
        ),
    ),
)


# ---------------------------------------------------------------------------
# Header alias registry (applies across all sheets, column-header level)
# ---------------------------------------------------------------------------

#: Maps known misspelled / legacy column headers to their canonical form.
#: Exact match is always tried first; fuzzy matching is never performed.
HEADER_ALIASES: dict[str, str] = {
    "Resonse": "Response",
    "Instantace Type": "Instance Type",
}


# ---------------------------------------------------------------------------
# Inspection result types
# ---------------------------------------------------------------------------


class InspectionOutcome(str, Enum):
    """Top-level result of workbook inspection."""

    VALID = "VALID"
    INVALID = "INVALID"        # Reject immediately; do not ingest.
    QUARANTINE = "QUARANTINE"  # Store but flag for human review.


@dataclass(frozen=True)
class SheetPresence:
    """
    Reports whether a contract-required sheet was found in the workbook.

    Attributes:
        canonical_name: The contract's canonical name for this sheet.
        role:           Functional role assigned by the contract.
        present:        True if the sheet was located (by canonical name or alias).
        alias_used:     The alias matched, or None if canonical name matched directly.
    """

    canonical_name: str
    role: SheetRole
    present: bool
    alias_used: str | None = None


@dataclass(frozen=True)
class WorkbookInspectionResult:
    """
    Immutable summary of a single workbook inspection run.

    Attributes:
        outcome:          Overall verdict (VALID / INVALID / QUARANTINE).
        contract_version: Matched contract identifier, or None if undetermined.
        sheet_presence:   Per-sheet presence report for every contract sheet.
        has_macros:       True if macro-enabled content type was detected.
        has_encryption:   True if any ZIP entry carries the encryption flag.
        has_external_links: True if external link content type was detected.
        compressed_bytes: Size of the raw uploaded stream in bytes.
        expanded_bytes:   Sum of uncompressed entry sizes across all ZIP entries.
        sheet_count:      Number of worksheets found in xl/workbook.xml.
        errors:           Tuple of fatal error messages (non-empty → INVALID).
        warnings:         Tuple of non-fatal finding messages.
    """

    outcome: InspectionOutcome
    contract_version: str | None
    sheet_presence: tuple[SheetPresence, ...]
    has_macros: bool
    has_encryption: bool
    has_external_links: bool
    compressed_bytes: int
    expanded_bytes: int
    sheet_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
