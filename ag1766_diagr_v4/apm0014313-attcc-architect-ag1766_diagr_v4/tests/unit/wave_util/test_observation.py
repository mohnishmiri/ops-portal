"""
Unit tests for domain/wave_util_observation.py — WaveUtil observation and
derived lineage (V02).

TDD RED: written before implementation; ImportError expected until
src/migration_intake/domain/wave_util_observation.py exists.

Architecture references: sections 18.2 and 20 of the production foundation
design document.

Required tests (15):
  1.  test_valid_cpu_pct_parses_correctly
  2.  test_cached_error_gives_cached_error_outcome
  3.  test_blank_field_gives_blank_outcome
  4.  test_negative_value_gives_invalid_outcome
  5.  test_cpu_above_100_produces_anomaly_finding
  6.  test_p95_above_max_produces_anomaly_finding
  7.  test_ram_exceeds_total_produces_anomaly_finding
  8.  test_missing_metric_without_reason_produces_finding
  9.  test_missing_metric_with_reason_no_finding
  10. test_window_unknown_when_no_dates
  11. test_window_known_when_start_provided
  12. test_no_algorithm_version_gives_derived_unverified
  13. test_algorithm_version_present_no_unverified_finding
  14. test_from_raw_all_blank_produces_no_anomaly_findings
  15. test_from_raw_valid_row_produces_no_findings
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from migration_intake.domain.wave_util_observation import (
    LineageFinding,
    LineageFindingType,
    MeasurementWindow,
    MetricObservation,
    ObservationOutcome,
    WaveUtilRowLineage,
    parse_metric_observation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_lineage(**kwargs: object) -> WaveUtilRowLineage:
    """Return a WaveUtilRowLineage built by from_raw with safe defaults.

    Defaults:
    - algorithm_version="v1.0" (so DERIVED_UNVERIFIED findings don't appear
      unless the test overrides it).
    - All metric raws=None (BLANK observations).
    - measurement_window=None.
    - All missing_reason fields=None.

    Pass keyword overrides to target a specific behaviour.
    """
    defaults: dict[str, object] = {
        "server_name": "SRV001",
        "cpu_raw": None,
        "ram_raw": None,
        "storage_raw": None,
        "network_raw": None,
        "p95_latency_raw": None,
        "max_latency_raw": None,
        "total_ram_raw": None,
        "measurement_window": None,
        "algorithm_version": "v1.0",
        "cpu_missing_reason": None,
        "ram_missing_reason": None,
        "storage_missing_reason": None,
        "network_missing_reason": None,
    }
    defaults.update(kwargs)
    return WaveUtilRowLineage.from_raw(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# Test 1 — valid decimal string → PARSED_OK and correct Decimal value
# ===========================================================================


class TestValidCpuPctParsesCorrectly:
    def test_valid_cpu_pct_parses_correctly(self) -> None:
        """'75.5' → parsed_value=Decimal('75.5'), parse_outcome=PARSED_OK."""
        obs = parse_metric_observation("75.5", "cpu_pct")
        assert obs.parsed_value == Decimal("75.5")
        assert obs.parse_outcome == ObservationOutcome.PARSED_OK


# ===========================================================================
# Test 2 — Excel cached-error string → CACHED_ERROR, parsed_value=None
# ===========================================================================


class TestCachedErrorGivesCachedErrorOutcome:
    def test_cached_error_gives_cached_error_outcome(self) -> None:
        """'#VALUE!' → parse_outcome=CACHED_ERROR, parsed_value=None."""
        obs = parse_metric_observation("#VALUE!", "cpu_pct")
        assert obs.parse_outcome == ObservationOutcome.CACHED_ERROR
        assert obs.parsed_value is None

    def test_div_zero_error_also_cached_error(self) -> None:
        """'#DIV/0!' → CACHED_ERROR (second well-known Excel error form)."""
        obs = parse_metric_observation("#DIV/0!", "memory_gb")
        assert obs.parse_outcome == ObservationOutcome.CACHED_ERROR
        assert obs.parsed_value is None


# ===========================================================================
# Test 3 — blank/empty string → BLANK, parsed_value=None
# ===========================================================================


class TestBlankFieldGivesBlankOutcome:
    def test_blank_field_gives_blank_outcome(self) -> None:
        """Empty string → parse_outcome=BLANK, parsed_value=None."""
        obs = parse_metric_observation("", "cpu_pct")
        assert obs.parse_outcome == ObservationOutcome.BLANK
        assert obs.parsed_value is None

    def test_none_input_gives_blank_outcome(self) -> None:
        """None → parse_outcome=BLANK, parsed_value=None."""
        obs = parse_metric_observation(None, "cpu_pct")
        assert obs.parse_outcome == ObservationOutcome.BLANK
        assert obs.parsed_value is None

    def test_whitespace_only_gives_blank_outcome(self) -> None:
        """Whitespace-only string → BLANK (treated as absent)."""
        obs = parse_metric_observation("   ", "cpu_pct")
        assert obs.parse_outcome == ObservationOutcome.BLANK
        assert obs.parsed_value is None


# ===========================================================================
# Test 4 — negative value → INVALID, parsed_value=None
# ===========================================================================


class TestNegativeValueGivesInvalidOutcome:
    def test_negative_value_gives_invalid_outcome(self) -> None:
        """'-1.5' → parse_outcome=INVALID (parse_decimal rejects negatives)."""
        obs = parse_metric_observation("-1.5", "cpu_pct")
        assert obs.parse_outcome == ObservationOutcome.INVALID
        assert obs.parsed_value is None

    def test_nan_gives_invalid_outcome(self) -> None:
        """'NaN' → INVALID (parse_decimal rejects NaN)."""
        obs = parse_metric_observation("NaN", "disk_gb")
        assert obs.parse_outcome == ObservationOutcome.INVALID

    def test_infinity_gives_invalid_outcome(self) -> None:
        """'Inf' → INVALID (parse_decimal rejects infinity)."""
        obs = parse_metric_observation("Inf", "network_mbps")
        assert obs.parse_outcome == ObservationOutcome.INVALID

    def test_comma_locale_gives_invalid_outcome(self) -> None:
        """'1,234.56' → INVALID (ambiguous locale separator)."""
        obs = parse_metric_observation("1,234.56", "storage_gb")
        assert obs.parse_outcome == ObservationOutcome.INVALID


# ===========================================================================
# Test 5 — CPU utilization > 100 % → OBSERVATION_ANOMALY finding
# ===========================================================================


class TestCpuAbove100ProducesAnomalyFinding:
    def test_cpu_above_100_produces_anomaly_finding(self) -> None:
        """CPU 105.0% exceeds the physical maximum → OBSERVATION_ANOMALY."""
        lineage = _minimal_lineage(cpu_raw="105.0")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and f.field_name == "cpu"
        ]
        assert len(anomaly_findings) >= 1

    def test_cpu_exactly_100_produces_no_anomaly(self) -> None:
        """CPU 100.0% is on the boundary — no anomaly."""
        lineage = _minimal_lineage(cpu_raw="100.0")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and f.field_name == "cpu"
        ]
        assert len(anomaly_findings) == 0

    def test_cpu_below_100_produces_no_anomaly(self) -> None:
        """CPU 75.0% is well within range — no anomaly."""
        lineage = _minimal_lineage(cpu_raw="75.0")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and f.field_name == "cpu"
        ]
        assert len(anomaly_findings) == 0


# ===========================================================================
# Test 6 — p95 latency > max latency → OBSERVATION_ANOMALY finding
# ===========================================================================


class TestP95AboveMaxProducesAnomalyFinding:
    def test_p95_above_max_produces_anomaly_finding(self) -> None:
        """p95=200ms > max=100ms → OBSERVATION_ANOMALY on latency field."""
        lineage = _minimal_lineage(p95_latency_raw="200", max_latency_raw="100")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and "latency" in f.field_name
        ]
        assert len(anomaly_findings) >= 1

    def test_p95_equal_to_max_produces_no_anomaly(self) -> None:
        """p95=100ms == max=100ms → boundary case, no anomaly."""
        lineage = _minimal_lineage(p95_latency_raw="100", max_latency_raw="100")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and "latency" in f.field_name
        ]
        assert len(anomaly_findings) == 0

    def test_p95_below_max_produces_no_anomaly(self) -> None:
        """p95=50ms < max=100ms → correct ordering, no anomaly."""
        lineage = _minimal_lineage(p95_latency_raw="50", max_latency_raw="100")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and "latency" in f.field_name
        ]
        assert len(anomaly_findings) == 0


# ===========================================================================
# Test 7 — observed peak RAM > total RAM → OBSERVATION_ANOMALY finding
# ===========================================================================


class TestRamExceedsTotalProducesAnomalyFinding:
    def test_ram_exceeds_total_produces_anomaly_finding(self) -> None:
        """Observed peak RAM 128 GB > total RAM 64 GB → OBSERVATION_ANOMALY."""
        lineage = _minimal_lineage(ram_raw="128", total_ram_raw="64")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and "ram" in f.field_name
        ]
        assert len(anomaly_findings) >= 1

    def test_ram_equals_total_produces_no_anomaly(self) -> None:
        """Observed peak RAM == total RAM → boundary, no anomaly."""
        lineage = _minimal_lineage(ram_raw="64", total_ram_raw="64")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and "ram" in f.field_name
        ]
        assert len(anomaly_findings) == 0

    def test_ram_below_total_produces_no_anomaly(self) -> None:
        """Observed peak RAM 16 GB < total RAM 32 GB → no anomaly."""
        lineage = _minimal_lineage(ram_raw="16", total_ram_raw="32")
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
            and "ram" in f.field_name
        ]
        assert len(anomaly_findings) == 0


# ===========================================================================
# Test 8 — missing metric with no reason → MISSING_METRIC_REASON finding
# ===========================================================================


class TestMissingMetricWithoutReasonProducesFinding:
    def test_missing_metric_without_reason_produces_finding(self) -> None:
        """cpu=None (blank), cpu_missing_reason=None → MISSING_METRIC_REASON."""
        lineage = _minimal_lineage(cpu_raw=None, cpu_missing_reason=None)
        missing_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.MISSING_METRIC_REASON
            and f.field_name == "cpu"
        ]
        assert len(missing_findings) >= 1

    def test_missing_ram_without_reason_produces_finding(self) -> None:
        """ram=None, ram_missing_reason=None → MISSING_METRIC_REASON for ram."""
        lineage = _minimal_lineage(ram_raw=None, ram_missing_reason=None)
        missing_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.MISSING_METRIC_REASON
            and f.field_name == "ram"
        ]
        assert len(missing_findings) >= 1


# ===========================================================================
# Test 9 — missing metric WITH reason provided → no MISSING_METRIC_REASON
# ===========================================================================


class TestMissingMetricWithReasonNoFinding:
    def test_missing_metric_with_reason_no_finding(self) -> None:
        """cpu=None, cpu_missing_reason='Not measured' → no MISSING_METRIC_REASON
        finding for the cpu field."""
        lineage = _minimal_lineage(
            cpu_raw=None,
            cpu_missing_reason="Not measured",
        )
        missing_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.MISSING_METRIC_REASON
            and f.field_name == "cpu"
        ]
        assert len(missing_findings) == 0

    def test_missing_ram_with_reason_no_finding(self) -> None:
        """ram=None, ram_missing_reason='Monitoring agent not installed' → no
        MISSING_METRIC_REASON for ram."""
        lineage = _minimal_lineage(
            ram_raw=None,
            ram_missing_reason="Monitoring agent not installed",
        )
        missing_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.MISSING_METRIC_REASON
            and f.field_name == "ram"
        ]
        assert len(missing_findings) == 0


# ===========================================================================
# Test 10 — MeasurementWindow with no dates → is_known == False
# ===========================================================================


class TestWindowUnknownWhenNoDates:
    def test_window_unknown_when_no_dates(self) -> None:
        """MeasurementWindow(None, None) → is_known == False."""
        window = MeasurementWindow(start_date=None, end_date=None)
        assert window.is_known is False

    def test_window_unknown_when_both_none_positional(self) -> None:
        """Positional args also produce is_known == False."""
        window = MeasurementWindow(None, None)
        assert window.is_known is False

    def test_window_with_description_only_still_unknown(self) -> None:
        """A description alone does not make a window known."""
        window = MeasurementWindow(
            start_date=None,
            end_date=None,
            description="Q1 2024 campaign",
        )
        assert window.is_known is False


# ===========================================================================
# Test 11 — MeasurementWindow with start date → is_known == True
# ===========================================================================


class TestWindowKnownWhenStartProvided:
    def test_window_known_when_start_provided(self) -> None:
        """MeasurementWindow(start_date=..., end_date=None) → is_known == True."""
        window = MeasurementWindow(start_date=date(2024, 1, 1), end_date=None)
        assert window.is_known is True

    def test_window_known_when_end_provided(self) -> None:
        """end_date alone is sufficient for is_known == True."""
        window = MeasurementWindow(start_date=None, end_date=date(2024, 1, 31))
        assert window.is_known is True

    def test_window_known_when_both_provided(self) -> None:
        """Both start and end → is_known == True."""
        window = MeasurementWindow(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert window.is_known is True


# ===========================================================================
# Test 12 — algorithm_version=None with a parsed value → DERIVED_UNVERIFIED
# ===========================================================================


class TestNoAlgorithmVersionGivesDerivedUnverified:
    def test_no_algorithm_version_gives_derived_unverified(self) -> None:
        """algorithm_version=None with a successfully parsed metric value →
        at least one LineageFinding of type DERIVED_UNVERIFIED."""
        lineage = _minimal_lineage(cpu_raw="75.5", algorithm_version=None)
        unverified_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.DERIVED_UNVERIFIED
        ]
        assert len(unverified_findings) >= 1

    def test_no_algorithm_with_all_blank_no_unverified_finding(self) -> None:
        """algorithm_version=None but all metrics blank → no DERIVED_UNVERIFIED
        (nothing was successfully parsed, so there is nothing to flag)."""
        lineage = _minimal_lineage(algorithm_version=None)
        unverified_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.DERIVED_UNVERIFIED
        ]
        assert len(unverified_findings) == 0


# ===========================================================================
# Test 13 — algorithm_version present → no DERIVED_UNVERIFIED finding
# ===========================================================================


class TestAlgorithmVersionPresentNoUnverifiedFinding:
    def test_algorithm_version_present_no_unverified_finding(self) -> None:
        """algorithm_version='v1.0' with parsed values → no DERIVED_UNVERIFIED
        findings regardless of other findings that may be present."""
        lineage = _minimal_lineage(cpu_raw="75.5", algorithm_version="v1.0")
        unverified_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.DERIVED_UNVERIFIED
        ]
        assert len(unverified_findings) == 0


# ===========================================================================
# Test 14 — all blank → only BLANK parse_outcomes, no OBSERVATION_ANOMALY
# ===========================================================================


class TestFromRawAllBlankProducesNoAnomalyFindings:
    def test_from_raw_all_blank_produces_no_anomaly_findings(self) -> None:
        """All metric raws are empty strings → all stored observations have
        parse_outcome==BLANK; no OBSERVATION_ANOMALY findings are generated."""
        lineage = WaveUtilRowLineage.from_raw(
            server_name="SRV001",
            cpu_raw="",
            ram_raw="",
            storage_raw="",
            network_raw="",
            p95_latency_raw="",
            max_latency_raw="",
            total_ram_raw="",
            measurement_window=None,
            algorithm_version=None,
        )

        # All four stored observations must be BLANK
        stored_observations = [
            lineage.cpu_observation,
            lineage.ram_observation,
            lineage.storage_observation,
            lineage.network_observation,
        ]
        for obs in stored_observations:
            if obs is not None:
                assert obs.parse_outcome == ObservationOutcome.BLANK, (
                    f"Expected BLANK but got {obs.parse_outcome!r} "
                    f"for observation with raw_text={obs.raw_text!r}"
                )

        # No anomaly findings
        anomaly_findings = [
            f for f in lineage.findings
            if f.finding_type == LineageFindingType.OBSERVATION_ANOMALY
        ]
        assert len(anomaly_findings) == 0


# ===========================================================================
# Test 15 — healthy row → empty findings tuple
# ===========================================================================


class TestFromRawValidRowProducesNoFindings:
    def test_from_raw_valid_row_produces_no_findings(self) -> None:
        """A fully valid, anomaly-free row with known window and algorithm
        version produces an empty findings tuple."""
        lineage = WaveUtilRowLineage.from_raw(
            server_name="SRV001",
            cpu_raw="75.5",      # below 100 → no anomaly
            ram_raw="16.0",      # 16 < total_ram 32 → no anomaly
            storage_raw="500.0",
            network_raw="1000.0",
            p95_latency_raw="50.0",   # 50 < max 100 → no anomaly
            max_latency_raw="100.0",
            total_ram_raw="32.0",
            measurement_window=MeasurementWindow(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            ),
            algorithm_version="v1.0",
            cpu_missing_reason=None,
            ram_missing_reason=None,
            storage_missing_reason=None,
            network_missing_reason=None,
        )
        assert lineage.findings == (), (
            f"Expected no findings but got: {lineage.findings!r}"
        )

    def test_valid_row_server_name_preserved(self) -> None:
        """server_name is stored verbatim on the lineage record."""
        lineage = WaveUtilRowLineage.from_raw(
            server_name="APPSERVER42",
            cpu_raw="50.0",
            ram_raw="8.0",
            storage_raw="200.0",
            network_raw="500.0",
            p95_latency_raw="20.0",
            max_latency_raw="40.0",
            total_ram_raw="16.0",
            measurement_window=MeasurementWindow(
                start_date=date(2024, 3, 1),
                end_date=date(2024, 3, 31),
            ),
            algorithm_version="v2.1",
        )
        assert lineage.server_name == "APPSERVER42"
        assert lineage.findings == ()
