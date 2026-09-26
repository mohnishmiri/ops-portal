"""HAF topology service — wires the DB extractor and fill pipeline.

This is the integration layer that bridges the database (via haf_extractor)
to the pure fill pipeline (via haf_pipeline). It is the single entry point
for topology generation from a web route or CLI.

Design rules:
- The session is passed in; the service does not create or manage transactions.
- Template bytes are passed in; the service does not read files from disk.
- The profile_id selects the profile config.
- Returns a typed result with filled XML, mutations, gaps, and extraction issues.

Updated 2026-09-25: Now passes interface_groups to the pipeline for grouped
protocol/port rendering of the ATT Internal Interfaces section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from migration_intake.topology.haf_extractor import extract_haf_data
from migration_intake.topology.haf_pipeline import (
    HafGap,
    HafMutation,
    fill_haf_template,
)
from migration_intake.topology.interface_normalization import (
    NormalizationReport,
    ProtocolFamilyGroup,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class HafTopologyResult:
    """Combined result of extraction + fill pipeline."""

    filled_xml: bytes
    tokens: dict[str, str]
    mutations: list[HafMutation]
    gaps: list[HafGap]
    extraction_issues: list[dict[str, Any]]
    success: bool
    # Interface groups for diagnostics
    interface_groups: list[ProtocolFamilyGroup] = field(default_factory=list)
    # AWS Tier 1 interface groups
    aws_interface_groups: list[ProtocolFamilyGroup] = field(default_factory=list)
    # New: normalization report for diagnostics
    normalization_report: NormalizationReport | None = None


def generate_haf_topology(
    *,
    session: Session,
    intake_id: str,
    profile_id: str,
    template_bytes: bytes,
) -> HafTopologyResult:
    """Generate a filled topology diagram from DB data and template.

    1. Extract tokens, interfaces, and details from DB.
    2. Run the fill pipeline with grouped interface rendering.
    3. Combine results.

    Args:
        session: Active SQLAlchemy session.
        intake_id: Intake to extract data for.
        profile_id: Profile identifier.
        template_bytes: Raw draw.io XML template bytes.

    Returns:
        HafTopologyResult with filled XML, mutations, gaps, and issues.
    """
    # Step 1: Extract data from DB (now includes interface_groups)
    extraction = extract_haf_data(session, intake_id, profile_id)

    # Step 2: Run the fill pipeline with grouped interfaces
    fill_result = fill_haf_template(
        template_bytes=template_bytes,
        tokens=extraction.tokens,
        interfaces=extraction.interfaces,
        details=extraction.details,
        profile_id=profile_id,
        interface_groups=extraction.interface_groups,
        aws_interface_groups=extraction.aws_interface_groups,
    )

    # Step 3: Combine
    return HafTopologyResult(
        filled_xml=fill_result.filled_xml,
        tokens=extraction.tokens,
        mutations=fill_result.mutations,
        gaps=fill_result.gaps,
        extraction_issues=extraction.issues,
        success=fill_result.success and not any(
            i.get("type") == "FATAL" for i in extraction.issues
        ),
        interface_groups=extraction.interface_groups,
        aws_interface_groups=extraction.aws_interface_groups,
        normalization_report=extraction.normalization_report,
    )
