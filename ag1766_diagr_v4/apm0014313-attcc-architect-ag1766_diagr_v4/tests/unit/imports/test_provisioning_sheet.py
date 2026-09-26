"""
Unit tests for Provisioning reference sheet adapter (B04).

All rows are synthetic — no client data used.
TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/provisioning_sheet.py exists.

Section 14.4 reference-data trap: Provisioning rows are staged as reference
data, never auto-adopted as application target placement.
"""
from __future__ import annotations

import pytest

from migration_intake.imports.provisioning_sheet import (
    ProvisioningCandidate,
    ProvisioningFinding,
    ProvisioningFindingType,
    ProvisioningSheetAdapter,
    ProvisioningSheetResult,
)


# ---------------------------------------------------------------------------
# Synthetic row factories — no client data
# ---------------------------------------------------------------------------


def _make_full_row(**overrides: str) -> dict:
    """Return a complete, valid synthetic Provisioning row."""
    row: dict = {
        "Physical Location": "Building A, Floor 3",
        "Data Center Code": "DC-ATL-01",
        "Data Center Name": "Atlanta Primary",
        "AWS Region": "us-east-1",
        "Region Display": "US East (N. Virginia)",
        "CLLI": "ATLNGAMQ",
        "Outpost ID": "op-0a1b2c3d4e5f67890",
        "Availability Zone": "us-east-1a",
        "Replication Target": "us-west-2",
    }
    row.update(overrides)
    return row


def _make_blank_row() -> dict:
    """Return a row where every value is an empty string."""
    return {
        "Physical Location": "",
        "Data Center Code": "",
        "Data Center Name": "",
        "AWS Region": "",
        "Region Display": "",
        "CLLI": "",
        "Outpost ID": "",
        "Availability Zone": "",
        "Replication Target": "",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvisioningSheetAdapter:
    # 1. A complete row produces a ProvisioningCandidate with correct fields.
    def test_valid_row_produces_candidate(self) -> None:
        adapter = ProvisioningSheetAdapter()
        result = adapter.parse([_make_full_row()])
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.physical_location == "Building A, Floor 3"
        assert c.dc_code == "DC-ATL-01"
        assert c.dc_name == "Atlanta Primary"
        assert c.aws_region == "us-east-1"
        assert c.clli == "ATLNGAMQ"
        assert c.outpost_id == "op-0a1b2c3d4e5f67890"
        assert c.availability_zone == "us-east-1a"
        assert c.replication_target == "us-west-2"

    # 2. All candidates always carry is_reference_data=True (section 14.4).
    def test_candidate_is_reference_data(self) -> None:
        adapter = ProvisioningSheetAdapter()
        result = adapter.parse([_make_full_row()])
        assert result.candidates[0].is_reference_data is True

    # 3. A malformed AWS region string produces an INVALID_REGION finding.
    def test_invalid_aws_region_produces_finding(self) -> None:
        adapter = ProvisioningSheetAdapter()
        result = adapter.parse([_make_full_row(**{"AWS Region": "not-a-region"})])
        region_findings = [
            f for f in result.findings
            if f.finding_type == ProvisioningFindingType.INVALID_REGION
        ]
        assert len(region_findings) == 1
        assert region_findings[0].row_number == 1

    # 4. A well-formed AWS region "us-east-1" is accepted with no INVALID_REGION.
    def test_valid_aws_region_accepted(self) -> None:
        adapter = ProvisioningSheetAdapter()
        result = adapter.parse([_make_full_row(**{"AWS Region": "us-east-1"})])
        region_findings = [
            f for f in result.findings
            if f.finding_type == ProvisioningFindingType.INVALID_REGION
        ]
        assert len(region_findings) == 0

    # 5. A row missing required fields produces an INCOMPLETE_ROW finding.
    def test_incomplete_row_produces_finding(self) -> None:
        adapter = ProvisioningSheetAdapter()
        row = _make_full_row(**{"Data Center Code": "", "AWS Region": ""})
        result = adapter.parse([row])
        incomplete = [
            f for f in result.findings
            if f.finding_type == ProvisioningFindingType.INCOMPLETE_ROW
        ]
        assert len(incomplete) == 1
        assert incomplete[0].row_number == 1

    # 6. The same (dc_code, aws_region) pair appearing twice → DUPLICATE_MAPPING.
    def test_duplicate_dc_code_region_produces_finding(self) -> None:
        adapter = ProvisioningSheetAdapter()
        row1 = _make_full_row()   # DC-ATL-01 / us-east-1
        row2 = _make_full_row()   # DC-ATL-01 / us-east-1 (identical pair)
        result = adapter.parse([row1, row2])
        dupes = [
            f for f in result.findings
            if f.finding_type == ProvisioningFindingType.DUPLICATE_MAPPING
        ]
        assert len(dupes) >= 1
        # The duplicate finding must identify the second row
        assert any(f.row_number == 2 for f in dupes)

    # 7. Same dc_code with two different aws_regions → CONTRADICTORY_MAPPING.
    def test_contradictory_dc_code_produces_finding(self) -> None:
        adapter = ProvisioningSheetAdapter()
        row1 = _make_full_row(**{"AWS Region": "us-east-1"})   # DC-ATL-01
        row2 = _make_full_row(**{"AWS Region": "eu-west-1"})   # DC-ATL-01, different region
        result = adapter.parse([row1, row2])
        contradictory = [
            f for f in result.findings
            if f.finding_type == ProvisioningFindingType.CONTRADICTORY_MAPPING
        ]
        assert len(contradictory) >= 1
        assert any(f.row_number == 2 for f in contradictory)

    # 8. source_locator uses "Sheet:Provisioning/Row:{n}" format.
    def test_source_locator_format(self) -> None:
        adapter = ProvisioningSheetAdapter()
        row1 = _make_full_row()
        row2 = _make_full_row(**{"Data Center Code": "DC-ATL-02"})  # distinct dc_code
        result = adapter.parse([row1, row2])
        assert result.candidates[0].source_locator == "Sheet:Provisioning/Row:1"
        assert result.candidates[1].source_locator == "Sheet:Provisioning/Row:2"

    # 9. The result type carries NO selected_target attribute — application target
    #    placement must be an explicit architect command (section 14.3).
    def test_does_not_auto_select_target_placement(self) -> None:
        adapter = ProvisioningSheetAdapter()
        result = adapter.parse([_make_full_row()])
        assert not hasattr(result, "selected_target")

    # 10. Blank row (all values empty) is silently discarded — no candidate, no finding.
    def test_blank_row_is_skipped(self) -> None:
        adapter = ProvisioningSheetAdapter()
        result = adapter.parse([_make_blank_row()])
        assert len(result.candidates) == 0
        blank_findings = [
            f for f in result.findings
            if f.finding_type == ProvisioningFindingType.BLANK_ROW
        ]
        assert len(blank_findings) == 0
