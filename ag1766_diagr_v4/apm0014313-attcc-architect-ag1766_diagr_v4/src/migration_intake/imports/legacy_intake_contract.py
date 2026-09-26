"""
Legacy intake workbook contract inspection.

Recognizes the exact seven-sheet APP_DATA_CAPTURE_LEGACY_V1 contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class LegacyIntakeContractVersion(StrEnum):
    """Supported legacy intake workbook versions."""

    V1 = "APP_DATA_CAPTURE_LEGACY_V1"


@dataclass(frozen=True)
class LegacyIntakeSheetContract:
    """Expected structure for one sheet in the legacy workbook."""

    canonical_name: str
    required: bool
    expected_headers: tuple[str, ...] | None = None


# The exact seven-sheet contract
LEGACY_INTAKE_V1_SHEETS = (
    LegacyIntakeSheetContract(
        canonical_name="App",
        required=True,
        expected_headers=("No", "Question", "Response_Type", "Response", "Allowed_Values_or_Unit"),
    ),
    LegacyIntakeSheetContract(
        canonical_name="iTAP",
        required=True,
        expected_headers=("Item", "Details"),
    ),
    LegacyIntakeSheetContract(
        canonical_name="WaveUtil",
        required=True,
        expected_headers=None,  # Variable structure
    ),
    LegacyIntakeSheetContract(
        canonical_name="Infra",
        required=True,
        expected_headers=None,
    ),
    LegacyIntakeSheetContract(
        canonical_name="Database",
        required=True,
        expected_headers=None,
    ),
    LegacyIntakeSheetContract(
        canonical_name="TSS",
        required=True,
        expected_headers=None,
    ),
    LegacyIntakeSheetContract(
        canonical_name="Provisioning",
        required=True,
        expected_headers=None,
    ),
)


class LegacyIntakeContractError(ValueError):
    """Raised when a workbook does not match the legacy intake contract."""


def inspect_legacy_intake_contract(
    sheet_names: list[str],
    sheet_headers: dict[str, tuple[Any, ...] | None],
) -> LegacyIntakeContractVersion:
    """
    Inspect workbook structure and determine if it matches the legacy contract.

    Args:
        sheet_names: List of sheet names in the workbook.
        sheet_headers: Dict of sheet_name -> first row tuple (or None if empty).

    Returns:
        LegacyIntakeContractVersion if matched.

    Raises:
        LegacyIntakeContractError: If the contract is not recognized.
    """
    # Check for required sheets
    sheet_set = set(sheet_names)
    required_sheets = {s.canonical_name for s in LEGACY_INTAKE_V1_SHEETS if s.required}

    missing = required_sheets - sheet_set
    if missing:
        raise LegacyIntakeContractError(
            f"Missing required sheets for legacy intake contract: {', '.join(sorted(missing))}"
        )

    # Check headers for sheets with expected structure
    for sheet_contract in LEGACY_INTAKE_V1_SHEETS:
        if sheet_contract.expected_headers is None:
            continue

        if sheet_contract.canonical_name not in sheet_headers:
            raise LegacyIntakeContractError(
                f"Sheet '{sheet_contract.canonical_name}' has no headers"
            )

        actual_headers = sheet_headers[sheet_contract.canonical_name]
        if actual_headers is None:
            raise LegacyIntakeContractError(
                f"Sheet '{sheet_contract.canonical_name}' is empty"
            )

        # Normalize headers (strip whitespace, case-insensitive comparison)
        expected = tuple(str(h).strip() for h in sheet_contract.expected_headers)
        actual = tuple(str(h).strip() if h else "" for h in actual_headers[: len(expected)])

        # Some completed workbooks use the original no-underscore spelling.
        if sheet_contract.canonical_name == "App":
            aliases = {2: "ResponseType", 3: "Resonse"}
            for index, alias in aliases.items():
                if len(actual) > index and actual[index] == alias:
                    actual = (*actual[:index], expected[index], *actual[index + 1:])

        if actual != expected:
            raise LegacyIntakeContractError(
                f"Sheet '{sheet_contract.canonical_name}' has unexpected headers. "
                f"Expected: {expected}, got: {actual}"
            )

    return LegacyIntakeContractVersion.V1


def is_legacy_intake_workbook(sheet_names: list[str]) -> bool:
    """
    Quick check if a workbook might be a legacy intake workbook.

    This is a fast pre-check before full inspection.
    """
    required_sheets = {"App", "iTAP", "WaveUtil", "Infra", "Database", "TSS", "Provisioning"}
    return required_sheets.issubset(set(sheet_names))
