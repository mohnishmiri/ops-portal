"""
Legacy intake identity resolution with precedence and cross-ID consistency.

Resolves application identity using Correlation first, then MOTS, then iTAP,
and validates that all supplied identifiers are consistent.
"""
from __future__ import annotations

from dataclasses import dataclass

from migration_intake.imports.legacy_intake_identity import (
    ExtractedIdentifier,
    consolidate_identifiers_by_type,
    get_unique_identifier_value,
    normalize_identifier,
)
from migration_intake.imports.source_identity import IdentityDecision


@dataclass(frozen=True)
class LegacyIdentityResolution:
    """
    Result of legacy intake identity resolution.

    Attributes:
        outcome: Identity decision (MATCHED, MISSING, MISMATCH, AMBIGUOUS, SOURCE_CONFLICT).
        selected_identifier_type: Which type was used for matching (CORRELATION, MOTS, ITAP).
        selected_raw_value: Raw value of the selected identifier.
        selected_normalized_value: Normalized value of the selected identifier.
        matched_application_ids: List of application IDs that matched.
        all_extracted_identifiers: All identifiers extracted from the workbook.
        conflict_detail: Description of any conflicts found.
    """

    outcome: IdentityDecision
    selected_identifier_type: str | None
    selected_raw_value: str | None
    selected_normalized_value: str | None
    matched_application_ids: tuple[str, ...]
    all_extracted_identifiers: tuple[ExtractedIdentifier, ...]
    conflict_detail: str | None = None


def resolve_legacy_intake_identity(
    *,
    extracted_identifiers: list[ExtractedIdentifier],
    application_identifiers: list[tuple[str, str, str]],
    selected_application_id: str | None = None,
) -> LegacyIdentityResolution:
    """
    Resolve application identity from legacy intake workbook identifiers.

    Precedence:
    1. Correlation ID (if present)
    2. MOTS ID (if Correlation absent)
    3. iTAP ID (if both Correlation and MOTS absent)

    All supplied identifiers must be consistent with the matched application.

    Args:
        extracted_identifiers: List of ExtractedIdentifier from the workbook.
        application_identifiers: List of (application_id, identifier_type, raw_value)
            from the database.
        selected_application_id: If provided, the matched application must equal this.

    Returns:
        LegacyIdentityResolution with outcome and matched application(s).
    """
    # Group identifiers by type
    by_type = consolidate_identifiers_by_type(extracted_identifiers)

    # Check for conflicts within each type
    correlation_value: tuple[str, str] | None = None
    mots_value: tuple[str, str] | None = None
    itap_value: tuple[str, str] | None = None

    try:
        if "CORRELATION" in by_type:
            correlation_value = get_unique_identifier_value(by_type["CORRELATION"])
        if "MOTS" in by_type:
            mots_value = get_unique_identifier_value(by_type["MOTS"])
        if "ITAP" in by_type:
            itap_value = get_unique_identifier_value(by_type["ITAP"])
    except ValueError as e:
        # Conflict within a single type
        return LegacyIdentityResolution(
            outcome=IdentityDecision.SOURCE_CONFLICT,
            selected_identifier_type=None,
            selected_raw_value=None,
            selected_normalized_value=None,
            matched_application_ids=(),
            all_extracted_identifiers=tuple(extracted_identifiers),
            conflict_detail=str(e),
        )

    # Determine which identifier to use (precedence)
    selected_type: str | None = None
    selected_raw: str | None = None
    selected_normalized: str | None = None

    if correlation_value:
        selected_type = "CORRELATION"
        selected_raw, selected_normalized = correlation_value
    elif mots_value:
        selected_type = "MOTS"
        selected_raw, selected_normalized = mots_value
    elif itap_value:
        selected_type = "ITAP"
        selected_raw, selected_normalized = itap_value

    # If no identifier found
    if not selected_type or not selected_normalized:
        return LegacyIdentityResolution(
            outcome=IdentityDecision.MISSING,
            selected_identifier_type=None,
            selected_raw_value=None,
            selected_normalized_value=None,
            matched_application_ids=(),
            all_extracted_identifiers=tuple(extracted_identifiers),
        )

    # Match against application identifiers
    matches = _match_identifier(
        identifier_type=selected_type,
        normalized_value=selected_normalized,
        application_identifiers=application_identifiers,
    )

    # Determine outcome
    if len(matches) > 1:
        outcome = IdentityDecision.AMBIGUOUS
    elif not matches or (selected_application_id and matches[0] != selected_application_id):
        outcome = IdentityDecision.MISMATCH
    else:
        outcome = IdentityDecision.MATCHED

    # If matched, validate cross-ID consistency
    if outcome == IdentityDecision.MATCHED:
        matched_app_id = matches[0]

        # Check if other supplied IDs are consistent
        conflict = _check_cross_id_consistency(
            matched_application_id=matched_app_id,
            correlation_value=correlation_value,
            mots_value=mots_value,
            itap_value=itap_value,
            application_identifiers=application_identifiers,
        )

        if conflict:
            return LegacyIdentityResolution(
                outcome=IdentityDecision.SOURCE_CONFLICT,
                selected_identifier_type=selected_type,
                selected_raw_value=selected_raw,
                selected_normalized_value=selected_normalized,
                matched_application_ids=tuple(matches),
                all_extracted_identifiers=tuple(extracted_identifiers),
                conflict_detail=conflict,
            )

    return LegacyIdentityResolution(
        outcome=outcome,
        selected_identifier_type=selected_type,
        selected_raw_value=selected_raw,
        selected_normalized_value=selected_normalized,
        matched_application_ids=tuple(matches),
        all_extracted_identifiers=tuple(extracted_identifiers),
    )


def _match_identifier(
    identifier_type: str,
    normalized_value: str,
    application_identifiers: list[tuple[str, str, str]],
) -> list[str]:
    """
    Match a normalized identifier against application identifiers.

    Returns:
        List of matching application IDs.
    """
    matches = []
    for app_id, id_type, raw_value in application_identifiers:
        if id_type.upper() == identifier_type.upper():
            if normalize_identifier(raw_value) == normalized_value:
                matches.append(app_id)

    return sorted(set(matches))


def _check_cross_id_consistency(
    matched_application_id: str,
    correlation_value: tuple[str, str] | None,
    mots_value: tuple[str, str] | None,
    itap_value: tuple[str, str] | None,
    application_identifiers: list[tuple[str, str, str]],
) -> str | None:
    """
    Check if all supplied identifiers are consistent with the matched application.

    Returns:
        Conflict description if inconsistent, None if all consistent.
    """
    # Check each supplied identifier type
    for id_type, value_tuple in [
        ("CORRELATION", correlation_value),
        ("MOTS", mots_value),
        ("ITAP", itap_value),
    ]:
        if value_tuple is None:
            continue

        _, normalized = value_tuple
        matches = _match_identifier(id_type, normalized, application_identifiers)

        if matches and matched_application_id not in matches:
            return (
                f"{id_type} identifier resolves to different application(s): "
                f"{', '.join(matches)} (expected {matched_application_id})"
            )

    return None
