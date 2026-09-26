"""
Hardcoded extension question mappings for Infra and Database sheets (B05).

Mappings are versioned code reviewed with the workbook contract.
Every nonblank row in either sheet gets a deterministic disposition:
    MAP_TO_QUESTION, MAP_TO_REGISTER_FIELD, SUPPORTING_EVIDENCE,
    DUPLICATE, RETIRED, UNMAPPED, AMBIGUOUS.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtensionMapping:
    """One versioned mapping entry for a legacy extension question."""

    contract_version: str
    sheet: str                          # "Infra" or "Database"
    normalized_question_anchor: str
    legacy_number: str | None
    expected_category: str
    disposition: str                    # one of the 7 canonical dispositions
    target_question_code: str | None    # for MAP_TO_QUESTION
    target_register_field: str | None   # for MAP_TO_REGISTER_FIELD
    transformation: str | None
    scope_rule: str | None
    notes: str


# ---------------------------------------------------------------------------
# Minimal synthetic mapping table (drives tests; not real client config)
# ---------------------------------------------------------------------------

EXTENSION_MAPPINGS: list[ExtensionMapping] = [
    ExtensionMapping(
        contract_version="APP_DATA_CAPTURE_V1",
        sheet="Infra",
        normalized_question_anchor="Operating System",
        legacy_number="INF-001",
        expected_category="TECHNICAL",
        disposition="MAP_TO_QUESTION",
        target_question_code="ENV-001",
        target_register_field=None,
        transformation=None,
        scope_rule=None,
        notes="Maps OS field to catalog environment question",
    ),
    ExtensionMapping(
        contract_version="APP_DATA_CAPTURE_V1",
        sheet="Infra",
        normalized_question_anchor="Is RAC Configured",
        legacy_number="INF-002",
        expected_category="DATABASE",
        disposition="MAP_TO_REGISTER_FIELD",
        target_question_code=None,
        target_register_field="db_rac_configured",
        transformation=None,
        scope_rule=None,
        notes="RAC configuration detail",
    ),
    ExtensionMapping(
        contract_version="APP_DATA_CAPTURE_V1",
        sheet="Database",
        normalized_question_anchor="Is RAC, Data Guard, or standby DB configured?",
        legacy_number="DB-001",
        expected_category="DATABASE",
        disposition="DUPLICATE",
        target_question_code=None,
        target_register_field="db_rac_configured",
        transformation=None,
        scope_rule=None,
        notes="Known duplicate row in Database sheet",
    ),
    ExtensionMapping(
        contract_version="APP_DATA_CAPTURE_V1",
        sheet="Infra",
        normalized_question_anchor="Legacy Hardware Note",
        legacy_number="INF-010",
        expected_category="TECHNICAL",
        disposition="RETIRED",
        target_question_code=None,
        target_register_field=None,
        transformation=None,
        scope_rule=None,
        notes="Legacy question retired in v0.2 catalog",
    ),
]


def get_mapping(sheet: str, normalized_anchor: str) -> ExtensionMapping | None:
    """Look up a mapping by sheet and normalized question anchor.

    Args:
        sheet:             "Infra" or "Database".
        normalized_anchor: Whitespace-normalized question text.

    Returns:
        The matching ExtensionMapping, or None if not found.
    """
    for m in EXTENSION_MAPPINGS:
        if m.sheet == sheet and m.normalized_question_anchor == normalized_anchor:
            return m
    return None
