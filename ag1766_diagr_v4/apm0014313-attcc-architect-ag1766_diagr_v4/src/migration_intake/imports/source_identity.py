"""Deterministic source-to-application identity decisions for imports."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IdentityDecision(StrEnum):
    """Identity verdict controlling whether answer candidates may be reviewed."""

    MATCHED = "APPLICATION_MATCHED"
    MISSING = "APPLICATION_ID_MISSING"
    MISMATCH = "APPLICATION_MISMATCH"
    AMBIGUOUS = "AMBIGUOUS_APPLICATION_MATCH"
    SOURCE_CONFLICT = "SOURCE_ID_CONFLICT"


@dataclass(frozen=True)
class SourceIdentityDecision:
    """Raw and normalized source identity plus its deterministic verdict."""

    outcome: IdentityDecision
    raw_source_id: str
    normalized_source_id: str
    matched_application_ids: tuple[str, ...] = ()


def normalize_identifier(value: str) -> str:
    """Normalize external IDs using the application identifier policy."""
    return "".join(character for character in value.casefold() if character.isalnum())


def compare_source_identity(
    *,
    source_id: str | None,
    application_identifiers: list[tuple[str, str, str]],
    selected_application_id: str | None = None,
) -> SourceIdentityDecision:
    """Compare a source ID to typed application identifiers.

    ``application_identifiers`` contains ``(application_id, type, raw_value)``.
    """
    raw_value = source_id or ""
    normalized = normalize_identifier(raw_value)
    if not normalized:
        return SourceIdentityDecision(IdentityDecision.MISSING, raw_value, normalized)

    matches = tuple(sorted({
        application_id
        for application_id, identifier_type, identifier_value in application_identifiers
        if identifier_type.casefold() == "correlation"
        and normalize_identifier(identifier_value) == normalized
    }))
    if len(matches) > 1:
        outcome = IdentityDecision.AMBIGUOUS
    elif not matches or (selected_application_id and matches[0] != selected_application_id):
        outcome = IdentityDecision.MISMATCH
    else:
        outcome = IdentityDecision.MATCHED
    return SourceIdentityDecision(outcome, raw_value, normalized, matches)
