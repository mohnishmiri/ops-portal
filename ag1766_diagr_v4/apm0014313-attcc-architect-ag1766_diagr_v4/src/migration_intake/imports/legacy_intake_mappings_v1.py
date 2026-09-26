"""
Legacy intake workbook field mappings — Version 1.

This module defines the exact, reviewed mappings from legacy App Data Capture
workbook fields to canonical catalog questions and registers.

Design rules:
- Every mapping is explicit and versioned
- Unknown fields produce findings, not candidates
- Mappings are deterministic and reproducible
- No AI inference for structured legacy data
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class LegacyMappingVersion(StrEnum):
    """Supported legacy mapping versions."""

    V1 = "LEGACY_MAPPING_V1"


class TargetKind(StrEnum):
    """Target type for a mapping."""

    QUESTION = "QUESTION"
    REGISTER = "REGISTER"
    METADATA = "METADATA"
    IDENTITY = "IDENTITY"  # Already handled by identity extraction


@dataclass(frozen=True)
class LegacyFieldMapping:
    """
    A single field mapping from legacy workbook to canonical target.

    Attributes:
        source_sheet: Sheet name (App, iTAP, TSS, Provisioning, etc.)
        source_field: Field identifier (question number, item name, etc.)
        source_label: Human-readable field label
        target_kind: What this maps to (QUESTION, REGISTER, METADATA, IDENTITY)
        target_key: Question code, register code, or metadata key
        value_transformer: Optional function name for value transformation
        scope: Optional scope (environment, site, etc.)
        notes: Implementation notes
    """

    source_sheet: str
    source_field: str
    source_label: str
    target_kind: TargetKind
    target_key: str | None
    value_transformer: str | None = None
    scope: dict[str, Any] | None = None
    notes: str = ""


# ═════════════════════════════════════════════════════════════════════════════
# App Sheet Mappings
# ═════════════════════════════════════════════════════════════════════════════

APP_SHEET_MAPPINGS: tuple[LegacyFieldMapping, ...] = (
    # Q1: Identity is also a canonical control answer. Identity extraction
    # still uses this row to match the application before review begins.
    LegacyFieldMapping(
        source_sheet="App",
        source_field="1",
        source_label="What is the application correlation or MOTS ID?",
        target_kind=TargetKind.QUESTION,
        target_key="CTL-001",
        value_transformer="parse_text",
        notes="Identity extraction and canonical control answer",
    ),
    # Q2: Application name and acronym is a canonical control answer.
    LegacyFieldMapping(
        source_sheet="App",
        source_field="2",
        source_label="What are the approved application name and acronym?",
        target_kind=TargetKind.QUESTION,
        target_key="CTL-002",
        value_transformer="parse_text_pair",
        notes="Verify against application record during review",
    ),
    # Q3: Required deliverables
    LegacyFieldMapping(
        source_sheet="App",
        source_field="3",
        source_label="What deliverables are required for this intake?",
        target_kind=TargetKind.QUESTION,
        target_key="CTL-003",
        value_transformer="parse_multi_select",
        notes="Maps to catalog question about required deliverables",
    ),
    # Q4: Business function
    LegacyFieldMapping(
        source_sheet="App",
        source_field="4",
        source_label="What business function does the application provide?",
        target_kind=TargetKind.QUESTION,
        target_key="APP-001",
        value_transformer="parse_long_text",
    ),
    # Q5: IT owner and contacts
    LegacyFieldMapping(
        source_sheet="App",
        source_field="5",
        source_label="Who are the IT application owner and primary technical contacts?",
        target_kind=TargetKind.QUESTION,
        target_key="APP-002",
        value_transformer="parse_people_list",
    ),
    # Q6: Operational status
    LegacyFieldMapping(
        source_sheet="App",
        source_field="6",
        source_label="What is the current operational status?",
        target_kind=TargetKind.QUESTION,
        target_key="APP-003",
        value_transformer="parse_single_select",
    ),
    # Q7: Business criticality and emergency tier
    LegacyFieldMapping(
        source_sheet="App",
        source_field="7",
        source_label="What are the business criticality and emergency tier?",
        target_kind=TargetKind.QUESTION,
        target_key="APP-004",
        value_transformer="parse_controlled_pair",
    ),
    # Q10: Customer facing
    LegacyFieldMapping(
        source_sheet="App",
        source_field="10",
        source_label="Is the application customer facing?",
        target_kind=TargetKind.QUESTION,
        target_key="APP-007",
        value_transformer="parse_boolean",
    ),
    # Q11: Internet facing
    LegacyFieldMapping(
        source_sheet="App",
        source_field="11",
        source_label="Is the application internet facing?",
        target_kind=TargetKind.QUESTION,
        target_key="APP-008",
        value_transformer="parse_boolean",
    ),
)

# ═════════════════════════════════════════════════════════════════════════════
# iTAP Sheet Mappings
# ═════════════════════════════════════════════════════════════════════════════

ITAP_SHEET_MAPPINGS: tuple[LegacyFieldMapping, ...] = (
    # Identity fields are also surfaced as control-question proposals where
    # the workbook carries a canonical MOTS value.
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="Correlation ID",
        source_label="Correlation ID",
        target_kind=TargetKind.IDENTITY,
        target_key=None,
        notes="Handled by identity extraction",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="APM Number",
        source_label="APM Number",
        target_kind=TargetKind.IDENTITY,
        target_key=None,
        notes="Handled by identity extraction (iTAP ID)",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="MOTS ID",
        source_label="MOTS ID",
        target_kind=TargetKind.QUESTION,
        target_key="CTL-001",
        value_transformer="parse_text",
        notes="Identity extraction and canonical control answer",
    ),
    # Metadata fields
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="Application acronym",
        source_label="Application acronym",
        target_kind=TargetKind.METADATA,
        target_key="application_acronym",
        notes="Verify against application record",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="Application name",
        source_label="Application name",
        target_kind=TargetKind.METADATA,
        target_key="application_name",
        notes="Verify against application record",
    ),
    # Question mappings
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="Emergency tier",
        source_label="Emergency tier",
        target_kind=TargetKind.QUESTION,
        target_key="APP-004",
        value_transformer="parse_text",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="Business criticality",
        source_label="Business criticality",
        target_kind=TargetKind.QUESTION,
        target_key="APP-004",
        value_transformer="parse_text",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="PCI data",
        source_label="PCI data",
        target_kind=TargetKind.QUESTION,
        target_key="APP_PCI_DATA",
        value_transformer="parse_boolean",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="SOX/FSA in-scope",
        source_label="SOX/FSA in-scope",
        target_kind=TargetKind.QUESTION,
        target_key="APP_SOX_FSA_SCOPE",
        value_transformer="parse_boolean",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="DR Priority",
        source_label="DR Priority",
        target_kind=TargetKind.QUESTION,
        target_key="APP_DR_PRIORITY",
        value_transformer="parse_text",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="DR RTO",
        source_label="DR RTO",
        target_kind=TargetKind.QUESTION,
        target_key="APP_DR_RTO",
        value_transformer="parse_duration",
    ),
    LegacyFieldMapping(
        source_sheet="iTAP",
        source_field="DR RPO",
        source_label="DR RPO",
        target_kind=TargetKind.QUESTION,
        target_key="APP_DR_RPO",
        value_transformer="parse_duration",
    ),
)

# ═════════════════════════════════════════════════════════════════════════════
# TSS Sheet Mappings
# ═════════════════════════════════════════════════════════════════════════════

# TSS sheet appears to be empty in the sample workbook
# Mappings can be added when structure is confirmed

TSS_SHEET_MAPPINGS: tuple[LegacyFieldMapping, ...] = ()

# ═════════════════════════════════════════════════════════════════════════════
# Provisioning Sheet Mappings
# ═════════════════════════════════════════════════════════════════════════════

# Provisioning sheet has site/datacenter information
# This appears to be a different structure (site rows, not questions)
# Needs further analysis - may map to infrastructure register

PROVISIONING_SHEET_MAPPINGS: tuple[LegacyFieldMapping, ...] = (
    # Placeholder - structure needs confirmation
)

# ═════════════════════════════════════════════════════════════════════════════
# Master Mapping Registry
# ═════════════════════════════════════════════════════════════════════════════

LEGACY_MAPPINGS_V1: dict[str, tuple[LegacyFieldMapping, ...]] = {
    "App": APP_SHEET_MAPPINGS,
    "iTAP": ITAP_SHEET_MAPPINGS,
    "TSS": TSS_SHEET_MAPPINGS,
    "Provisioning": PROVISIONING_SHEET_MAPPINGS,
}

# Target names used by the first legacy importer. Keep these aliases readable
# so already-imported proposals remain reviewable after the mappings are fixed.
LEGACY_TARGET_ALIASES: dict[str, str] = {
    "APP_DELIVERABLES": "CTL-003",
    "APP_BUSINESS_FUNCTION": "APP-001",
    "APP_IT_CONTACTS": "APP-002",
    "APP_OPERATIONAL_STATUS": "APP-003",
    "APP_CRITICALITY_TIER": "APP-004",
    "APP_EMERGENCY_TIER": "APP-004",
    "APP_BUSINESS_CRITICALITY": "APP-004",
    "APP_CUSTOMER_FACING": "APP-007",
    "APP_INTERNET_FACING": "APP-008",
    "APP_PCI_DATA": "SEC-004",
    "APP_SOX_FSA_SCOPE": "SEC-008",
    "APP_DR_PRIORITY": "RES-001",
    "APP_DR_RTO": "RES-001",
    "APP_DR_RPO": "RES-001",
}


def canonical_target_key(target_key: str) -> str:
    """Resolve a legacy target name to the current catalog question code."""
    return LEGACY_TARGET_ALIASES.get(target_key, target_key)


def get_mapping_for_field(
    sheet_name: str,
    field_identifier: str,
) -> LegacyFieldMapping | None:
    """
    Get the mapping for a specific field.

    Args:
        sheet_name: Sheet name (App, iTAP, etc.)
        field_identifier: Field identifier (question number, item name, etc.)

    Returns:
        LegacyFieldMapping if found, None if unknown field.
    """
    sheet_mappings = LEGACY_MAPPINGS_V1.get(sheet_name, ())

    for mapping in sheet_mappings:
        if mapping.source_field == field_identifier:
            return mapping

    return None


def get_all_mapped_fields(sheet_name: str) -> set[str]:
    """
    Get all mapped field identifiers for a sheet.

    Returns:
        Set of field identifiers that have mappings.
    """
    sheet_mappings = LEGACY_MAPPINGS_V1.get(sheet_name, ())
    return {mapping.source_field for mapping in sheet_mappings}
