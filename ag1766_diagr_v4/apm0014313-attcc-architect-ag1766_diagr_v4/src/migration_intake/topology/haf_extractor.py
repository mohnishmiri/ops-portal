"""HAF topology data extractor — bridges the database to the haf pipeline.

Extracts tokens, interfaces, and detail block data from the database
for a given intake, in the shape expected by ``haf_pipeline.fill_haf_template()``.

Design rules:
- This is the ONLY module that touches the database for the haf pipeline.
- The pipeline module (``haf_pipeline.py``) remains a pure function.
- Uses existing ORM models and adapter patterns.
- Never invents missing values; missing data is listed in ``issues``.

Updated 2026-09-25: Uses HAF-specific location aliases from interface_normalization
module to correctly classify Midrange/Hybrid/Private/Conexus/OnPrem as INTERNAL
for the AT&T Internal Interfaces section per Topology Guide requirements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text

from migration_intake.persistence.models import (
    AnswerInstance,
    AnswerRevision,
    ApplicationIdentifier,
    CatalogQuestion,
)
from migration_intake.persistence.models_interfaces import InterfaceRecord
from migration_intake.topology.haf_pipeline import load_haf_profile
from migration_intake.topology.interface_normalization import (
    HAF_LOCATION_ALIASES,
    InterfaceCandidate,
    InterfaceGroup,
    NormalizationReport,
    ProtocolFamilyGroup,
    create_interface_candidate,
    group_interfaces_by_protocol_family,
    group_interfaces_by_protocol_port,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class HafExtractionResult:
    """Data extracted from the DB for the haf pipeline."""

    tokens: dict[str, str] = field(default_factory=dict)
    interfaces: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    details: dict[str, dict[str, str]] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    # Grouped interfaces for ATT Internal section (protocol-family grouping)
    interface_groups: list[ProtocolFamilyGroup] = field(default_factory=list)
    # Grouped interfaces for AWS Tier 1 section (inbound + bidirectional)
    aws_interface_groups: list[ProtocolFamilyGroup] = field(default_factory=list)
    # New: all interface candidates for diagnostics
    interface_candidates: list[InterfaceCandidate] = field(default_factory=list)
    # New: normalization report for diagnostics
    normalization_report: NormalizationReport | None = None


# Maps question codes (in DB) to haf pipeline token names.
# This extends the existing FACT_REGISTRY with haf-pipeline-specific tokens.
QUESTION_TO_HAF_TOKEN: dict[str, str] = {
    "VPC_CIDR": "vpc_cidr",
    "SUBNET_CIDR": "subnet_cidr",
    "OUTPOST_CIDR": "outpost_cidr",
    "TARGET_ENVIRONMENT": "environment",
    "TARGET_REGION": "region",
    "AWS_REGION": "region",
    "DB_ENGINE": "db_engine",
    "EC2_INSTANCE_TYPE": "ec2_instance_type",
    "EC2_COUNT": "ec2_count",
}

# Maps identifier types to haf pipeline token names.
IDENTIFIER_TO_HAF_TOKEN: dict[str, str] = {
    "CORRELATION": "correlation_id",
    "ACRONYM": "app_acronym",
    "MOTS": "mots_id",
}


def extract_haf_data(
    session: Session,
    intake_id: str,
    profile_id: str,
) -> HafExtractionResult:
    """Extract tokens, interfaces, and details for the haf pipeline.

    Args:
        session: Active SQLAlchemy session.
        intake_id: Intake to extract data for.
        profile_id: Profile to load (determines which tokens are expected).

    Returns:
        HafExtractionResult with tokens, interfaces, details, and issues.
    """
    result = HafExtractionResult()
    profile = load_haf_profile(profile_id)

    # Load intake and application — use targeted columns to avoid migration gaps
    intake_row = session.execute(
        text(
            "SELECT i.id, i.application_id, a.display_name "
            "FROM intakes i JOIN applications a ON a.id = i.application_id "
            "WHERE i.id = :intake_id"
        ),
        {"intake_id": intake_id},
    ).first()

    if intake_row is None:
        result.issues.append({"type": "FATAL", "message": f"Intake {intake_id} not found"})
        return result

    application_id = str(intake_row[1])
    result.tokens["app_name"] = str(intake_row[2])

    # Extract tokens from identifiers
    identifiers = (
        session.execute(
            select(ApplicationIdentifier)
            .where(ApplicationIdentifier.application_id == application_id)
        )
        .scalars()
        .all()
    )
    for ident in identifiers:
        ident_type = str(ident.identifier_type).upper()
        token_name = IDENTIFIER_TO_HAF_TOKEN.get(ident_type)
        if token_name:
            result.tokens[token_name] = str(ident.raw_value)

    # Extract tokens from answers
    answers_query = (
        select(AnswerInstance, AnswerRevision, CatalogQuestion)
        .join(AnswerRevision, AnswerRevision.id == AnswerInstance.current_rev_id)
        .join(CatalogQuestion, CatalogQuestion.id == AnswerInstance.question_id)
        .where(AnswerInstance.intake_id == intake_id)
    )
    for row in session.execute(answers_query).all():
        revision = row[1]
        question = row[2]
        question_code = str(question.question_code).upper()
        token_name = QUESTION_TO_HAF_TOKEN.get(question_code)
        if token_name is None:
            continue

        value = _extract_answer_value(revision)
        if value:
            result.tokens[token_name] = value

    # Check for missing tokens that the profile expects
    expected_tokens = {b.token for b in profile.placeholder_bindings}
    for token in sorted(expected_tokens):
        if token not in result.tokens:
            result.issues.append({
                "type": "MISSING_TOKEN",
                "token": token,
                "message": f"No DB answer or identifier for token {token!r}",
            })

    # Extract interfaces grouped by category and direction
    # Uses HAF-specific location aliases that include guide-required values
    # (Midrange/Hybrid/Private/Conexus/OnPrem → INTERNAL)
    interface_rows = (
        session.execute(
            select(InterfaceRecord)
            .where(
                InterfaceRecord.application_id == application_id,
                InterfaceRecord.state == "ACTIVE",
            )
        )
        .scalars()
        .all()
    )

    # Create normalized candidates for all interfaces
    normalization_report = NormalizationReport()
    candidates: list[InterfaceCandidate] = []

    for iface in interface_rows:
        candidate = create_interface_candidate(
            interface_system_location=iface.interface_system_location,
            data_traffic_direction=iface.data_traffic_direction,
            target_protocol=iface.target_protocol,
            future_port=iface.future_port,
            interface_app_acronym=iface.interface_app_acronym,
            interface_correlation_id=iface.interface_correlation_id,
        )
        candidates.append(candidate)
        normalization_report.add_candidate(candidate)

    # Store candidates and report for diagnostics
    result.interface_candidates = candidates
    result.normalization_report = normalization_report

    # Group interfaces by protocol family for ATT Internal section
    result.interface_groups = group_interfaces_by_protocol_family(candidates)
    normalization_report.groups_created = len(result.interface_groups)

    # Group interfaces by protocol family for AWS Tier 1 section
    # Only inbound + bidirectional interfaces with AWS location
    result.aws_interface_groups = group_interfaces_by_protocol_family(
        candidates,
        category_filter="AWS",
        direction_filter=frozenset({"INBOUND", "BIDIRECTIONAL"}),
    )

    # Log normalization summary
    normalization_report.log_summary()

    # Build legacy interface dict for backward compatibility
    # Uses HAF_LOCATION_ALIASES which includes guide-required locations
    for candidate in candidates:
        key = f"{candidate.norm_category}:{candidate.norm_direction}"
        entry = {
            "app_name": candidate.interface_app_acronym or "",
            "correlation_id": candidate.interface_correlation_id or "",
        }
        result.interfaces.setdefault(key, []).append(entry)

    # Sort interface lists for determinism
    for key in result.interfaces:
        result.interfaces[key].sort(
            key=lambda e: (e.get("app_name", ""), e.get("correlation_id", ""))
        )

    return result


def _extract_answer_value(revision: Any) -> str | None:
    """Extract the text value from an answer revision's response_json."""
    import json

    raw = getattr(revision, "response_json", None)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            return parsed.get("value") or parsed.get("first")
        return str(parsed) if parsed else None
    except (json.JSONDecodeError, TypeError):
        return str(raw) if raw else None


def _normalize_direction(raw: str | None) -> str:
    """Normalize direction to the guide_policy canonical form."""
    if not raw:
        return "UNKNOWN"
    normalized = raw.strip().upper()
    if normalized in ("INBOUND", "IN"):
        return "INBOUND"
    if normalized in ("OUTBOUND", "OUT"):
        return "OUTBOUND"
    if normalized in ("BIDIRECTIONAL", "IN_OUT", "BOTH"):
        return "BIDIRECTIONAL"
    return "UNKNOWN"
