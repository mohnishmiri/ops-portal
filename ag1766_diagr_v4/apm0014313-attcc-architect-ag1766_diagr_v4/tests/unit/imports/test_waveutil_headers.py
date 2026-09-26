"""
Unit tests for the WaveUtil sheet header contract and row parser (V01).

Tests validate_headers() and parse_row() on WaveUtilSheetAdapter.

TDD RED: written before implementation; ImportError expected until
src/migration_intake/imports/wave_util_sheet.py exists.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from migration_intake.domain.wave_util import (
    ApplicationEnvironment,
    BusinessCriticality,
)
from migration_intake.imports.wave_util_sheet import (
    WAVEUTIL_HEADERS,
    WaveUtilFindingType,
    WaveUtilSheetAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_raw_headers() -> list[str]:
    """Return all 34 raw header strings from WAVEUTIL_HEADERS."""
    return list(WAVEUTIL_HEADERS.keys())


def _make_adapter() -> WaveUtilSheetAdapter:
    return WaveUtilSheetAdapter()


def _make_row(**overrides: object) -> dict:
    """Minimal canonical-keyed row; only server_name by default."""
    base: dict = {"server_name": "SRV001"}
    base.update(overrides)
    return base


# ===========================================================================
# Test 1 — all required headers present → no missing, no unknown
# ===========================================================================


class TestAllRequiredHeadersPresent:
    def test_all_required_headers_present_is_valid(self) -> None:
        """Passing all 34 raw headers → missing_required=[], unknown_headers=[]."""
        adapter = _make_adapter()
        canonical, missing, unknown = adapter.validate_headers(_all_raw_headers())

        assert missing == [], f"Unexpected missing required headers: {missing}"
        assert unknown == [], f"Unexpected unknown headers: {unknown}"

    def test_all_34_resolve_to_canonical_names(self) -> None:
        """Every raw header in the full set resolves to a canonical field name."""
        adapter = _make_adapter()
        canonical, _missing, _unknown = adapter.validate_headers(_all_raw_headers())

        # All canonical names must be non-empty strings
        assert all(isinstance(c, str) and c for c in canonical)


# ===========================================================================
# Test 2 — missing required header is reported
# ===========================================================================


class TestMissingRequiredHeader:
    def test_missing_required_header_reported(self) -> None:
        """Omitting 'Server Name' headers → 'server_name' appears in missing_required."""
        adapter = _make_adapter()
        # Exclude both "Server Name" and "Server Name " (trailing-space variant)
        filtered = [
            h for h in _all_raw_headers()
            if h not in ("Server Name", "Server Name ")
        ]
        _canonical, missing, _unknown = adapter.validate_headers(filtered)

        assert "server_name" in missing, (
            f"Expected 'server_name' in missing_required, got: {missing}"
        )

    def test_all_three_required_present_when_server_name_included(self) -> None:
        """With 'Server Name', 'Mots Id', and 'Application' present, nothing is missing."""
        adapter = _make_adapter()
        # Use minimal subset that covers all three required headers
        minimal = ["Server Name", "Mots Id", "Application"]
        _canonical, missing, _unknown = adapter.validate_headers(minimal)

        assert missing == []


# ===========================================================================
# Test 3 — unknown header is reported
# ===========================================================================


class TestUnknownHeader:
    def test_unknown_header_reported(self) -> None:
        """A header not in WAVEUTIL_HEADERS → appears in unknown_headers."""
        adapter = _make_adapter()
        headers = _all_raw_headers() + ["UnknownFieldXYZ"]
        _canonical, _missing, unknown = adapter.validate_headers(headers)

        assert "UnknownFieldXYZ" in unknown

    def test_only_unknown_headers_excluded_from_canonical(self) -> None:
        """Unknown headers do not pollute the canonical list."""
        adapter = _make_adapter()
        headers = ["Server Name", "UnknownFieldXYZ"]
        canonical, _missing, unknown = adapter.validate_headers(headers)

        assert "server_name" in canonical
        assert "UnknownFieldXYZ" not in canonical
        assert "UnknownFieldXYZ" in unknown


# ===========================================================================
# Test 4 — "Instantace Type" (known typo alias) accepted without error
# ===========================================================================


class TestInstacaceTypeAlias:
    def test_instantace_type_alias_accepted_without_error(self) -> None:
        """The known typo header 'Instantace Type' must not appear in unknown_headers."""
        adapter = _make_adapter()
        _canonical, _missing, unknown = adapter.validate_headers(["Instantace Type"])

        assert "Instantace Type" not in unknown, (
            "'Instantace Type' is a known alias and must be accepted."
        )

    def test_instantace_type_maps_to_recommended_instance_type(self) -> None:
        adapter = _make_adapter()
        canonical, _missing, _unknown = adapter.validate_headers(["Instantace Type"])

        assert "recommended_instance_type" in canonical


# ===========================================================================
# Test 5 — "Server Name " (trailing space) accepted via explicit map entry
# ===========================================================================


class TestHeaderNormalizationTrailingSpace:
    def test_header_normalization_strips_trailing_space(self) -> None:
        """'Server Name ' (trailing space) is a known variant → maps to server_name."""
        adapter = _make_adapter()
        canonical, _missing, unknown = adapter.validate_headers(["Server Name "])

        assert "server_name" in canonical, (
            "'Server Name ' (trailing space) must resolve to 'server_name'."
        )
        assert "Server Name " not in unknown, (
            "'Server Name ' must not appear in unknown_headers."
        )

    def test_canonical_server_name_without_space_also_maps(self) -> None:
        """'Server Name' (no trailing space) also maps to server_name."""
        adapter = _make_adapter()
        canonical, _missing, unknown = adapter.validate_headers(["Server Name"])

        assert "server_name" in canonical
        assert "Server Name" not in unknown


# ===========================================================================
# Test 6 — valid row parses correctly into typed WaveUtilRowValues
# ===========================================================================


class TestRowWithValidFields:
    def test_row_with_valid_fields_parses_correctly(self) -> None:
        """Row with all key fields populated → WaveUtilRowValues with correct typed fields."""
        adapter = _make_adapter()
        row = {
            "server_name": "SRV001",
            "mots_id": "12345",
            "application_name": "MyApp",
            "source_hosting_platform": "AWS",
            "source_environment_type_raw": "Cloud",
            "application_environment": "Production",
            "source_data_center": "DC-EAST",
            "target_raw": "NYCMNY01",
            "business_criticality": "HIGH",
            "application_lifecycle": "Active",
            "operating_system": "Linux",
            "os_version": "8.1",
            "serial_number": "SN-ABCD",
            "cpu_allocated": "4",
            "cpu_cores": "8",
            "memory_allocated_gb": "16",
            "storage_allocated_gb": "200",
            "virtual_disk_count_or_raw": "3",
            "nic_count_or_raw": "2",
            "cpu_p95_percent": "75",
            "cpu_max_percent": "90",
            "memory_p95_gb": "12",
            "memory_max_gb": "14",
            "disk_p95_gb": "150",
            "disk_max_gb": "180",
            "recommended_vcpu": "4",
            "recommended_memory_gb": "16",
            "source_exception_flag": "No",
            "recommended_instance_type": "m5.xlarge",
            "final_allocated_vcpu": "4",
            "final_allocated_memory_gb": "16",
            "recommended_ebs_gb": "250",
            "recommended_target_dc": "us-east-1",
        }
        result = adapter.parse_row(row, row_number=2)

        assert result.values is not None

        # Identity
        assert result.values.identity.server_name == "SRV001"
        assert result.values.identity.mots_id == "12345"
        assert result.values.identity.application_name == "MyApp"
        assert result.values.identity.business_criticality == BusinessCriticality.HIGH
        assert result.values.identity.application_environment == ApplicationEnvironment.PRODUCTION
        assert result.values.identity.target_clli == "NYCMNY01"
        assert result.values.identity.target_disposition is None

        # Inventory — os_version stays as str
        assert result.values.inventory.os_version == "8.1"
        assert isinstance(result.values.inventory.os_version, str)
        assert result.values.inventory.cpu_allocated == Decimal("4")
        assert result.values.inventory.memory_allocated_gb == Decimal("16")

        # No findings for a clean row
        assert result.findings == (), f"Unexpected findings: {result.findings}"

    def test_row_number_propagated(self) -> None:
        """row_number is stored on WaveUtilRowResult."""
        adapter = _make_adapter()
        result = adapter.parse_row(_make_row(), row_number=7)
        assert result.row_number == 7


# ===========================================================================
# Test 7 — blank server_name produces MISSING_SERVER_NAME finding
# ===========================================================================


class TestRowWithBlankServerName:
    def test_row_with_blank_server_name_produces_finding(self) -> None:
        """Row with blank server_name → values=None + MISSING_SERVER_NAME finding."""
        adapter = _make_adapter()
        row: dict = {"server_name": ""}
        result = adapter.parse_row(row, row_number=3)

        assert result.values is None, "values must be None when server_name is blank"

        missing_findings = [
            f for f in result.findings
            if f.finding_type == WaveUtilFindingType.MISSING_SERVER_NAME
        ]
        assert len(missing_findings) == 1, (
            f"Expected 1 MISSING_SERVER_NAME finding, got: {result.findings}"
        )

    def test_whitespace_only_server_name_is_blank(self) -> None:
        """'   ' (whitespace only) is treated as blank server_name."""
        adapter = _make_adapter()
        row: dict = {"server_name": "   "}
        result = adapter.parse_row(row, row_number=4)

        assert result.values is None

    def test_missing_server_name_key_is_blank(self) -> None:
        """Row dict with no 'server_name' key at all → MISSING_SERVER_NAME."""
        adapter = _make_adapter()
        row: dict = {}
        result = adapter.parse_row(row, row_number=5)

        assert result.values is None
        missing_findings = [
            f for f in result.findings
            if f.finding_type == WaveUtilFindingType.MISSING_SERVER_NAME
        ]
        assert len(missing_findings) == 1
