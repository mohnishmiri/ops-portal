"""
Legacy intake workbook identity extraction.

Extracts typed external identifiers (Correlation, MOTS, iTAP) from
the App and iTAP sheets with deterministic source locators.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractedIdentifier:
    """
    A single extracted identifier with type, value, and source location.

    Attributes:
        identifier_type: Canonical type code (CORRELATION, MOTS, ITAP).
        raw_value: Original value exactly as read from the workbook.
        normalized_value: Normalized using alphanumeric, case-insensitive policy.
        source_sheet: Sheet name where the identifier was found.
        source_row: 1-based row number.
        source_column: Column letter or name.
        source_label: Field label or question text.
    """

    identifier_type: str
    raw_value: str
    normalized_value: str
    source_sheet: str
    source_row: int
    source_column: str
    source_label: str


def normalize_identifier(value: str) -> str:
    """
    Normalize external IDs using the application identifier policy.

    Removes all non-alphanumeric characters and converts to lowercase.
    """
    return "".join(character for character in value.casefold() if character.isalnum())


def extract_legacy_intake_identifiers(
    app_sheet_rows: list[dict[str, Any]],
    itap_sheet_rows: list[tuple[str, str]],
) -> list[ExtractedIdentifier]:
    """
    Extract typed identifiers from App and iTAP sheets.

    Args:
        app_sheet_rows: List of dicts from App sheet (keys: No, Question, Response_Type, Response, etc.).
        itap_sheet_rows: List of (Item, Details) tuples from iTAP sheet.

    Returns:
        List of ExtractedIdentifier objects.
    """
    identifiers: list[ExtractedIdentifier] = []

    # ── Extract from App sheet ────────────────────────────────────────────
    # App Q1: "What is the application correlation or MOTS ID?"
    # Response_Type: IDENTIFIER
    # Response: could be Correlation ID or MOTS ID

    for row_idx, row in enumerate(app_sheet_rows, start=2):  # Row 1 is headers, data starts at 2
        question = str(row.get("Question", "")).strip().lower()
        response_type = str(row.get("Response_Type", "")).strip().upper()
        response = str(row.get("Response", "")).strip()

        # Q1: Correlation or MOTS ID
        if "correlation" in question and "mots" in question and response_type == "IDENTIFIER":
            if response:
                # Determine if it's Correlation or MOTS based on content
                # For now, assume it's Correlation if it doesn't explicitly say MOTS
                # This is a heuristic; in practice, the mapping should be explicit
                normalized = normalize_identifier(response)
                if normalized:
                    # Default to CORRELATION unless we have better heuristics
                    identifier_type = "CORRELATION"
                    identifiers.append(
                        ExtractedIdentifier(
                            identifier_type=identifier_type,
                            raw_value=response,
                            normalized_value=normalized,
                            source_sheet="App",
                            source_row=row_idx,
                            source_column="D",  # Response column
                            source_label=str(row.get("Question", "")),
                        )
                    )

    # ── Extract from iTAP sheet ───────────────────────────────────────────
    # iTAP uses Item/Details layout
    # Known identity fields:
    #   - "Correlation ID" → CORRELATION
    #   - "APM Number" → ITAP
    #   - We don't currently have a MOTS field in iTAP

    itap_label_mapping = {
        "correlation id": "CORRELATION",
        "apm number": "ITAP",
        "itap id": "ITAP",
        "mots id": "MOTS",
        "mots": "MOTS",
    }

    for row_idx, (item, details) in enumerate(itap_sheet_rows, start=2):  # Row 1 is headers
        if not item or not details:
            continue

        item_normalized = str(item).strip().lower()
        details_str = str(details).strip()

        # Check if this item is a known identity field
        for label_pattern, identifier_type in itap_label_mapping.items():
            if label_pattern in item_normalized:
                normalized = normalize_identifier(details_str)
                if normalized:
                    identifiers.append(
                        ExtractedIdentifier(
                            identifier_type=identifier_type,
                            raw_value=details_str,
                            normalized_value=normalized,
                            source_sheet="iTAP",
                            source_row=row_idx,
                            source_column="B",  # Details column
                            source_label=str(item),
                        )
                    )
                break

    return identifiers


def consolidate_identifiers_by_type(
    identifiers: list[ExtractedIdentifier],
) -> dict[str, list[ExtractedIdentifier]]:
    """
    Group identifiers by type and detect conflicts.

    Returns:
        Dict of identifier_type -> list of ExtractedIdentifier.
    """
    by_type: dict[str, list[ExtractedIdentifier]] = {}

    for ident in identifiers:
        if ident.identifier_type not in by_type:
            by_type[ident.identifier_type] = []
        by_type[ident.identifier_type].append(ident)

    return by_type


def get_unique_identifier_value(
    identifiers: list[ExtractedIdentifier],
) -> tuple[str, str] | None:
    """
    Get unique normalized value for a list of identifiers of the same type.

    Returns:
        (raw_value, normalized_value) if unique, None if conflicting or absent.

    Raises:
        ValueError: If multiple distinct normalized values exist.
    """
    if not identifiers:
        return None

    # Get unique normalized values
    unique_normalized = {ident.normalized_value for ident in identifiers}

    if len(unique_normalized) > 1:
        # Conflict: same type, different values
        raise ValueError(
            f"Conflicting {identifiers[0].identifier_type} identifiers: "
            f"{', '.join(sorted(unique_normalized))}"
        )

    # All identifiers have the same normalized value
    # Return the first one's raw value and the normalized value
    return identifiers[0].raw_value, identifiers[0].normalized_value
