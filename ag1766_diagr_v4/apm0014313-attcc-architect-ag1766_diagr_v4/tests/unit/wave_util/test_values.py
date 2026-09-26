"""
Unit tests for domain/wave_util.py — WaveUtil value model (V01).

All 16 tests listed in the TDD plan are implemented here.
Tests 1–5 also import WAVEUTIL_HEADERS from wave_util_sheet to verify
the header contract aligns with domain canonical names.

TDD RED: written before implementation; ImportError expected until
src/migration_intake/domain/wave_util.py and imports/wave_util_sheet.py exist.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from migration_intake.domain.wave_util import (
    ApplicationEnvironment,
    BusinessCriticality,
    WaveUtilIdentityFields,
    WaveUtilInventoryFields,
    WaveUtilParseError,
    is_excel_cached_error,
    parse_business_criticality,
    parse_decimal,
    split_target_data_center,
)
from migration_intake.imports.wave_util_sheet import (
    WAVEUTIL_HEADERS,
    WaveUtilFindingType,
    WaveUtilSheetAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_row(**overrides: object) -> dict:
    """Return a canonical-field-keyed row dict with only server_name set.

    Extra kwargs are merged in, allowing targeted field injection.
    """
    base: dict = {"server_name": "SRV001"}
    base.update(overrides)
    return base


# ===========================================================================
# Test 1 — all 34 WAVEUTIL_HEADERS keys resolve to canonical field names
# ===========================================================================


class TestAll34Headers:
    def test_all_34_headers_map_to_canonical_fields(self) -> None:
        """WAVEUTIL_HEADERS must contain exactly 34 entries, each a non-empty str."""
        assert len(WAVEUTIL_HEADERS) == 34, (
            f"Expected 34 headers, got {len(WAVEUTIL_HEADERS)}"
        )
        for raw_header, canonical in WAVEUTIL_HEADERS.items():
            assert isinstance(canonical, str), (
                f"Header {raw_header!r} maps to non-str: {canonical!r}"
            )
            assert canonical, (
                f"Header {raw_header!r} maps to empty string"
            )


# ===========================================================================
# Test 2 — "Environment" header maps to "source_hosting_platform"
# ===========================================================================


class TestEnvironmentHeaderMapping:
    def test_environment_header_maps_to_source_hosting_platform(self) -> None:
        """'Environment' is semantically a hosting platform, not an env-type."""
        assert WAVEUTIL_HEADERS["Environment"] == "source_hosting_platform"


# ===========================================================================
# Test 3 — "Server Type" maps to "application_environment"
# ===========================================================================


class TestServerTypeHeaderMapping:
    def test_server_type_maps_to_application_environment(self) -> None:
        """'Server Type' raw header → canonical 'application_environment'."""
        assert WAVEUTIL_HEADERS["Server Type"] == "application_environment"


# ===========================================================================
# Test 4 — target_raw splits CLLI from disposition
# ===========================================================================


class TestSplitTargetDataCenter:
    def test_valid_clli_goes_to_target_clli(self) -> None:
        """8-char uppercase alphanumeric string → target_clli, disposition=None."""
        clli, disposition = split_target_data_center("NYCMNY01")
        assert clli == "NYCMNY01"
        assert disposition is None

    def test_disposition_text_goes_to_target_disposition(self) -> None:
        """'Decommission' is not a CLLI → target_clli=None, target_disposition set."""
        clli, disposition = split_target_data_center("Decommission")
        assert clli is None
        assert disposition == "Decommission"

    def test_none_raw_returns_none_tuple(self) -> None:
        clli, disposition = split_target_data_center(None)
        assert clli is None
        assert disposition is None

    def test_blank_raw_returns_none_tuple(self) -> None:
        clli, disposition = split_target_data_center("   ")
        assert clli is None
        assert disposition is None

    def test_11_char_clli_accepted(self) -> None:
        """11-character CLLI is within range."""
        clli, disposition = split_target_data_center("NYCMNY01ABC")
        assert clli == "NYCMNY01ABC"
        assert disposition is None

    def test_not_found_text_is_disposition(self) -> None:
        clli, disposition = split_target_data_center("Not Found")
        assert clli is None
        assert disposition == "Not Found"

    def test_target_data_center_splits_clli_from_disposition(self) -> None:
        """Combined assertion: valid CLLI and disposition text behave correctly."""
        clli_val, disp_val = split_target_data_center("NYCMNY01")
        assert clli_val == "NYCMNY01"
        assert disp_val is None

        clli_val2, disp_val2 = split_target_data_center("Decommission")
        assert clli_val2 is None
        assert disp_val2 == "Decommission"


# ===========================================================================
# Test 5 — "Instantace Type" (known typo) maps to recommended_instance_type
# ===========================================================================


class TestInstacaceTypeAlias:
    def test_instantace_type_known_alias(self) -> None:
        """'Instantace Type' (typo in source data) → 'recommended_instance_type'."""
        assert WAVEUTIL_HEADERS["Instantace Type"] == "recommended_instance_type"


# ===========================================================================
# Test 6 — os_version remains text, never coerced to numeric
# ===========================================================================


class TestOsVersionRemainsText:
    def test_os_version_remains_text(self) -> None:
        """os_version '8.1' must be stored as str, not converted to float."""
        inv = WaveUtilInventoryFields(
            operating_system=None,
            os_version="8.1",
            serial_number=None,
            cpu_allocated=None,
            cpu_cores=None,
            memory_allocated_gb=None,
            storage_allocated_gb=None,
            virtual_disk_count_or_raw=None,
            nic_count_or_raw=None,
        )
        assert inv.os_version == "8.1"
        assert isinstance(inv.os_version, str)

    def test_os_version_numeric_string_stays_string(self) -> None:
        """Any string that looks numeric still stays as str (no float coercion)."""
        inv = WaveUtilInventoryFields(
            operating_system="Windows",
            os_version="2019",
            serial_number=None,
            cpu_allocated=None,
            cpu_cores=None,
            memory_allocated_gb=None,
            storage_allocated_gb=None,
            virtual_disk_count_or_raw=None,
            nic_count_or_raw=None,
        )
        assert isinstance(inv.os_version, str)
        assert inv.os_version == "2019"


# ===========================================================================
# Test 7 — decimal fields reject negative values
# ===========================================================================


class TestDecimalRejectsNegative:
    def test_decimal_fields_reject_negative(self) -> None:
        """-1 → WaveUtilParseError; negative measurements are invalid."""
        with pytest.raises(WaveUtilParseError, match="[Nn]egative"):
            parse_decimal("-1", "cpu_allocated")

    def test_negative_float_string_rejected(self) -> None:
        with pytest.raises(WaveUtilParseError):
            parse_decimal("-0.01", "memory_allocated_gb")


# ===========================================================================
# Test 8 — decimal fields reject NaN
# ===========================================================================


class TestDecimalRejectsNaN:
    def test_decimal_fields_reject_nan(self) -> None:
        """'NaN' → WaveUtilParseError; NaN is not a valid measurement."""
        with pytest.raises(WaveUtilParseError, match="[Nn][Aa][Nn]"):
            parse_decimal("NaN", "cpu_allocated")

    def test_lowercase_nan_rejected(self) -> None:
        with pytest.raises(WaveUtilParseError):
            parse_decimal("nan", "cpu_p95_percent")


# ===========================================================================
# Test 9 — decimal fields reject infinity
# ===========================================================================


class TestDecimalRejectsInfinity:
    def test_decimal_fields_reject_infinity(self) -> None:
        """'Inf' → WaveUtilParseError; infinity is not a valid measurement."""
        with pytest.raises(WaveUtilParseError, match="[Ii]nfinit"):
            parse_decimal("Inf", "cpu_allocated")

    def test_full_infinity_string_rejected(self) -> None:
        with pytest.raises(WaveUtilParseError):
            parse_decimal("Infinity", "disk_p95_gb")


# ===========================================================================
# Test 10 — decimal fields reject ambiguous locale (comma separator)
# ===========================================================================


class TestDecimalRejectsAmbiguousLocale:
    def test_decimal_fields_reject_ambiguous_locale(self) -> None:
        """'1,234.56' (thousands comma) → WaveUtilParseError; use '1234.56'."""
        with pytest.raises(WaveUtilParseError, match="[Cc]omma|[Aa]mbiguous|[Ll]ocale"):
            parse_decimal("1,234.56", "cpu_allocated")

    def test_plain_decimal_is_accepted(self) -> None:
        """'1234.56' (no comma) parses successfully."""
        result = parse_decimal("1234.56", "cpu_allocated")
        assert result == Decimal("1234.56")


# ===========================================================================
# Test 11 — cached Excel errors produce CACHED_ERROR finding, not zero
# ===========================================================================


class TestCachedExcelErrors:
    def test_cached_excel_errors_are_invalid(self) -> None:
        """#DIV/0! for nic_count → CACHED_ERROR finding; value is None, not zero."""
        adapter = WaveUtilSheetAdapter()
        row = _make_minimal_row(nic_count_or_raw="#DIV/0!")
        result = adapter.parse_row(row, row_number=1)

        cached = [
            f for f in result.findings
            if f.finding_type == WaveUtilFindingType.CACHED_ERROR
        ]
        assert len(cached) == 1
        assert cached[0].field_name == "nic_count_or_raw"
        assert cached[0].raw_value == "#DIV/0!"

        # Value must be None, not zero or "0"
        assert result.values is not None
        assert result.values.inventory.nic_count_or_raw is None

    def test_value_error_excel_is_cached_error(self) -> None:
        """#VALUE! is also a cached Excel error, not a parseable value."""
        assert is_excel_cached_error("#VALUE!") is True

    def test_div_zero_is_cached_error(self) -> None:
        assert is_excel_cached_error("#DIV/0!") is True

    def test_normal_integer_is_not_excel_error(self) -> None:
        assert is_excel_cached_error("42") is False


# ===========================================================================
# Test 12 — blank decimal input returns None (not zero)
# ===========================================================================


class TestDecimalBlankIsNone:
    def test_decimal_blank_is_none(self) -> None:
        """Blank / None input → None, not 0 or Decimal('0')."""
        assert parse_decimal(None, "cpu_allocated") is None
        assert parse_decimal("", "cpu_allocated") is None
        assert parse_decimal("   ", "cpu_allocated") is None

    def test_valid_zero_is_accepted(self) -> None:
        """'0' is a valid decimal (zero allocation is meaningful)."""
        result = parse_decimal("0", "cpu_allocated")
        assert result == Decimal("0")


# ===========================================================================
# Test 13 — all BusinessCriticality codes accepted
# ===========================================================================


class TestBusinessCriticalityValidCodes:
    def test_business_criticality_valid_codes(self) -> None:
        """All five approved vocabulary entries parse without UNKNOWN fallback."""
        assert parse_business_criticality("CRITICAL") == BusinessCriticality.CRITICAL
        assert parse_business_criticality("HIGH") == BusinessCriticality.HIGH
        assert parse_business_criticality("MEDIUM") == BusinessCriticality.MEDIUM
        assert parse_business_criticality("LOW") == BusinessCriticality.LOW
        assert parse_business_criticality("UNKNOWN") == BusinessCriticality.UNKNOWN

    def test_case_insensitive_criticality(self) -> None:
        """'high' and 'High' both map to HIGH (case-insensitive)."""
        assert parse_business_criticality("high") == BusinessCriticality.HIGH
        assert parse_business_criticality("High") == BusinessCriticality.HIGH


# ===========================================================================
# Test 14 — unmapped raw criticality → UNKNOWN
# ===========================================================================


class TestBusinessCriticalityUnknownFallback:
    def test_business_criticality_unknown_for_unmapped(self) -> None:
        """'Very High' is not in the approved vocabulary → UNKNOWN."""
        assert parse_business_criticality("Very High") == BusinessCriticality.UNKNOWN

    def test_blank_criticality_is_unknown(self) -> None:
        assert parse_business_criticality(None) == BusinessCriticality.UNKNOWN
        assert parse_business_criticality("") == BusinessCriticality.UNKNOWN


# ===========================================================================
# Test 15 — ApplicationEnvironment: "Production" → PRODUCTION
# ===========================================================================


class TestApplicationEnvironmentProduction:
    def test_application_environment_production_maps_correctly(self) -> None:
        """'Production' → ApplicationEnvironment.PRODUCTION."""
        assert ApplicationEnvironment.normalize("Production") == ApplicationEnvironment.PRODUCTION

    def test_prod_abbreviation_maps_to_production(self) -> None:
        assert ApplicationEnvironment.normalize("prod") == ApplicationEnvironment.PRODUCTION

    def test_qa_maps_to_test(self) -> None:
        assert ApplicationEnvironment.normalize("QA") == ApplicationEnvironment.TEST


# ===========================================================================
# Test 16 — ApplicationEnvironment: "DR" → DR
# ===========================================================================


class TestApplicationEnvironmentDR:
    def test_application_environment_dr_maps_correctly(self) -> None:
        """'DR' (uppercase) → ApplicationEnvironment.DR."""
        assert ApplicationEnvironment.normalize("DR") == ApplicationEnvironment.DR

    def test_disaster_recovery_maps_to_dr(self) -> None:
        assert ApplicationEnvironment.normalize("Disaster Recovery") == ApplicationEnvironment.DR

    def test_unknown_environment_fallback(self) -> None:
        assert ApplicationEnvironment.normalize("Legacy") == ApplicationEnvironment.UNKNOWN
