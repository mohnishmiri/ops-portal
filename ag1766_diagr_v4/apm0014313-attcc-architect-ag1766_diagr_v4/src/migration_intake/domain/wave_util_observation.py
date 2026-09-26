"""
WaveUtil observation and derived lineage model (V02).

Defines explicit provenance for every numeric/measurement field extracted
from a WaveUtil spreadsheet row, and computes lineage findings that flag
anomalies, missing explanations, and unverified derivations.

Architecture references: sections 18.2 and 20 of the production foundation
design document.

Design invariants
-----------------
- This module does NOT modify wave_util.py (V01).
- ``parse_metric_observation`` is the public entry point for single-field
  parsing; it records raw text, parsed value, and parse outcome.
- ``WaveUtilRowLineage.from_raw`` assembles per-field observations, applies
  measurement-window context, and generates findings.
- No metric value may be negative; ``parse_decimal`` from wave_util.py
  enforces this and raises ``WaveUtilParseError`` for any violation.
- Anomalies are recorded as findings — never silently corrected.
- Blank metrics without a supplied missing-reason produce a
  ``MISSING_METRIC_REASON`` finding.
- Successfully parsed metrics without an algorithm/version produce a
  ``DERIVED_UNVERIFIED`` finding.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from migration_intake.domain.wave_util import (
    WaveUtilParseError,
    is_excel_cached_error,
    parse_decimal,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ObservationOutcome(str, Enum):
    """Classification of what the parser did with a raw cell value.

    ``PARSED_OK``
        Raw text parsed to a valid, non-negative finite Decimal.
    ``CACHED_ERROR``
        Raw text is a cached Excel formula error (e.g. ``#VALUE!``,
        ``#DIV/0!``); no numeric value could be extracted.
    ``BLANK``
        Raw text was ``None``, empty, or whitespace-only; value is absent.
    ``INVALID``
        Raw text was present but rejected: negative, NaN, infinity,
        locale-ambiguous comma, or otherwise unparseable.
    ``DERIVED_UNVERIFIED``
        Value was parsed but the algorithm/workbook version that produced it
        is unknown; the observation cannot satisfy sizing approval.
    ``WINDOW_UNKNOWN``
        Value was parsed but the measurement window (start/end date) is
        unknown; the observation is undefended.
    """

    PARSED_OK = "PARSED_OK"
    CACHED_ERROR = "CACHED_ERROR"
    BLANK = "BLANK"
    INVALID = "INVALID"
    DERIVED_UNVERIFIED = "DERIVED_UNVERIFIED"
    WINDOW_UNKNOWN = "WINDOW_UNKNOWN"


class LineageFindingType(str, Enum):
    """Types of lineage findings attached to a ``WaveUtilRowLineage``.

    ``OBSERVATION_ANOMALY``
        A parsed metric value violates a sanity constraint (e.g. CPU > 100%,
        p95 latency > max latency, or observed RAM > total RAM).
    ``MISSING_METRIC_REASON``
        A metric field is blank and no missing-reason explanation was supplied.
    ``DERIVED_UNVERIFIED``
        One or more metrics were successfully parsed but no algorithm/workbook
        version was provided; sizing approval cannot use these values.
    """

    OBSERVATION_ANOMALY = "OBSERVATION_ANOMALY"
    MISSING_METRIC_REASON = "MISSING_METRIC_REASON"
    DERIVED_UNVERIFIED = "DERIVED_UNVERIFIED"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricObservation:
    """Parsed representation of one numeric measurement cell.

    Attributes
    ----------
    raw_text:
        The original cell value as a string (formula text or display value).
        Empty string when the source was ``None`` or blank.
    parsed_value:
        Parsed ``Decimal`` value, or ``None`` when the cell was blank,
        invalid, or a cached Excel error.
    parse_outcome:
        Classification of what the parser did with ``raw_text``.
    algorithm_version:
        The algorithm or workbook version that produced any derived value.
        ``None`` when not known; from_raw sets this from its caller parameter.
    """

    raw_text: str
    parsed_value: Decimal | None
    parse_outcome: ObservationOutcome
    algorithm_version: str | None = None


@dataclass(frozen=True)
class MeasurementWindow:
    """Temporal context for a set of utilisation observations.

    Attributes
    ----------
    start_date:
        First date of the measurement period, or ``None`` when unknown.
    end_date:
        Last date of the measurement period, or ``None`` when unknown.
    description:
        Optional free-text description (e.g. "Q1 2024 steady-state window").
    """

    start_date: date | None
    end_date: date | None
    description: str = ""

    @property
    def is_known(self) -> bool:
        """Return ``True`` when at least one boundary date is present.

        A window with ``start_date`` *or* ``end_date`` is considered known.
        A description alone is insufficient — it does not anchor the window
        in calendar time.
        """
        return self.start_date is not None or self.end_date is not None


@dataclass(frozen=True)
class LineageFinding:
    """One anomaly or provenance issue attached to a ``WaveUtilRowLineage``.

    Attributes
    ----------
    finding_type:
        Category of the finding.
    field_name:
        Canonical field name where the issue was detected.
    detail:
        Human-readable explanation of the anomaly or gap.
    """

    finding_type: LineageFindingType
    field_name: str
    detail: str


@dataclass(frozen=True)
class WaveUtilRowLineage:
    """Computed lineage for the observation fields of one WaveUtil row.

    This record captures per-field MetricObservations (with parse provenance)
    and the LineageFindings generated by cross-field anomaly and completeness
    rules.

    Attributes
    ----------
    server_name:
        Server name from the source row; used as the record's natural key.
    cpu_observation:
        Parsed CPU utilisation observation, or ``None`` if not in scope.
    ram_observation:
        Parsed RAM utilisation observation, or ``None`` if not in scope.
    storage_observation:
        Parsed storage utilisation observation, or ``None`` if not in scope.
    network_observation:
        Parsed network throughput observation, or ``None`` if not in scope.
    measurement_window:
        Temporal context for all observations on this row.
    findings:
        Immutable tuple of all lineage findings; empty when the row is healthy.
    """

    server_name: str
    cpu_observation: MetricObservation | None
    ram_observation: MetricObservation | None
    storage_observation: MetricObservation | None
    network_observation: MetricObservation | None
    measurement_window: MeasurementWindow | None
    findings: tuple[LineageFinding, ...]

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_raw(
        cls,
        server_name: str,
        cpu_raw: str | None = None,
        ram_raw: str | None = None,
        storage_raw: str | None = None,
        network_raw: str | None = None,
        p95_latency_raw: str | None = None,
        max_latency_raw: str | None = None,
        total_ram_raw: str | None = None,
        measurement_window: MeasurementWindow | None = None,
        algorithm_version: str | None = None,
        cpu_missing_reason: str | None = None,
        ram_missing_reason: str | None = None,
        storage_missing_reason: str | None = None,
        network_missing_reason: str | None = None,
    ) -> WaveUtilRowLineage:
        """Parse raw cell values into a ``WaveUtilRowLineage`` record.

        Steps
        -----
        1. Parse each numeric field using :func:`parse_metric_observation`.
        2. Apply measurement-window context: when the window is not known and
           a metric parsed successfully, change its outcome to
           ``WINDOW_UNKNOWN``.
        3. Attach ``algorithm_version`` to every MetricObservation.
        4. Generate :class:`LineageFinding` entries for:
           - ``OBSERVATION_ANOMALY``: CPU > 100%, p95 latency > max latency,
             observed peak RAM > total RAM.
           - ``MISSING_METRIC_REASON``: stored metric is blank with no reason.
           - ``DERIVED_UNVERIFIED``: stored metric has a parsed value but
             ``algorithm_version`` is ``None``.

        Parameters
        ----------
        server_name:
            Server name from the source row.
        cpu_raw:
            Raw cell text for observed peak CPU utilisation (percent).
        ram_raw:
            Raw cell text for observed peak RAM usage (GB).
        storage_raw:
            Raw cell text for observed peak storage usage (GB).
        network_raw:
            Raw cell text for observed peak network throughput (Mbps).
        p95_latency_raw:
            Raw cell text for 95th-percentile latency (ms); used for the
            p95 > max anomaly check only — not stored as a named observation.
        max_latency_raw:
            Raw cell text for maximum latency (ms); used for the same check.
        total_ram_raw:
            Raw cell text for total allocated RAM (GB); used for the
            observed > total RAM anomaly check only.
        measurement_window:
            Temporal context for all observations on this row.
        algorithm_version:
            Algorithm or workbook version that produced derived values.
            ``None`` triggers a ``DERIVED_UNVERIFIED`` finding for every
            successfully parsed stored observation.
        cpu_missing_reason:
            Explanation for why the CPU metric is absent; suppresses the
            ``MISSING_METRIC_REASON`` finding for this field when provided.
        ram_missing_reason:
            Explanation for why the RAM metric is absent.
        storage_missing_reason:
            Explanation for why the storage metric is absent.
        network_missing_reason:
            Explanation for why the network metric is absent.

        Returns
        -------
        WaveUtilRowLineage
            Fully populated lineage record with all applicable findings.
        """
        window_known: bool = (
            measurement_window is not None and measurement_window.is_known
        )

        # ── Step 1: parse all raw cell values ────────────────────────────

        raw_cpu = parse_metric_observation(cpu_raw, "cpu")
        raw_ram = parse_metric_observation(ram_raw, "ram")
        raw_storage = parse_metric_observation(storage_raw, "storage")
        raw_network = parse_metric_observation(network_raw, "network")

        # Ancillary fields used for anomaly checks only (not stored as
        # named observations on the lineage record).
        raw_p95_lat = parse_metric_observation(p95_latency_raw, "p95_latency")
        raw_max_lat = parse_metric_observation(max_latency_raw, "max_latency")
        raw_total_ram = parse_metric_observation(total_ram_raw, "total_ram")

        # ── Step 2 & 3: apply window context and algorithm_version ───────

        def _contextualise(obs: MetricObservation) -> MetricObservation:
            """Return a new MetricObservation with window and algorithm context.

            If the metric has a successfully parsed value (PARSED_OK) but the
            measurement window is not known, the outcome is changed to
            WINDOW_UNKNOWN.  The algorithm_version is always attached.
            """
            if obs.parsed_value is None:
                # BLANK, CACHED_ERROR, or INVALID — window does not apply.
                return dataclasses.replace(obs, algorithm_version=algorithm_version)

            new_outcome = obs.parse_outcome
            if not window_known and new_outcome == ObservationOutcome.PARSED_OK:
                new_outcome = ObservationOutcome.WINDOW_UNKNOWN

            return dataclasses.replace(
                obs,
                parse_outcome=new_outcome,
                algorithm_version=algorithm_version,
            )

        cpu_obs = _contextualise(raw_cpu)
        ram_obs = _contextualise(raw_ram)
        storage_obs = _contextualise(raw_storage)
        network_obs = _contextualise(raw_network)

        # Ancillary observations — contextualise for consistent structure but
        # they are only used for cross-field anomaly checks below.
        p95_lat_obs = _contextualise(raw_p95_lat)
        max_lat_obs = _contextualise(raw_max_lat)
        total_ram_obs = _contextualise(raw_total_ram)

        # ── Step 4: generate findings ────────────────────────────────────

        findings: list[LineageFinding] = []

        # ── 4a: OBSERVATION_ANOMALY ──────────────────────────────────────

        # CPU utilisation > 100 % is physically impossible.
        if (
            cpu_obs.parsed_value is not None
            and cpu_obs.parsed_value > Decimal("100.0")
        ):
            findings.append(
                LineageFinding(
                    finding_type=LineageFindingType.OBSERVATION_ANOMALY,
                    field_name="cpu",
                    detail=(
                        f"Observed peak CPU utilisation {cpu_obs.parsed_value}% "
                        f"exceeds the physical maximum of 100%.  "
                        f"Verify the source formula or unit."
                    ),
                )
            )

        # p95 latency must not exceed the maximum latency for the same period.
        if (
            p95_lat_obs.parsed_value is not None
            and max_lat_obs.parsed_value is not None
            and p95_lat_obs.parsed_value > max_lat_obs.parsed_value
        ):
            findings.append(
                LineageFinding(
                    finding_type=LineageFindingType.OBSERVATION_ANOMALY,
                    field_name="p95_latency",
                    detail=(
                        f"p95 latency {p95_lat_obs.parsed_value} ms exceeds "
                        f"max latency {max_lat_obs.parsed_value} ms.  "
                        f"A 95th-percentile cannot exceed the maximum for the "
                        f"same observation window."
                    ),
                )
            )

        # Observed peak RAM must not exceed the machine's total RAM.
        if (
            ram_obs.parsed_value is not None
            and total_ram_obs.parsed_value is not None
            and ram_obs.parsed_value > total_ram_obs.parsed_value
        ):
            findings.append(
                LineageFinding(
                    finding_type=LineageFindingType.OBSERVATION_ANOMALY,
                    field_name="ram",
                    detail=(
                        f"Observed peak RAM {ram_obs.parsed_value} GB exceeds "
                        f"total allocated RAM {total_ram_obs.parsed_value} GB.  "
                        f"Verify units and source columns."
                    ),
                )
            )

        # ── 4b: MISSING_METRIC_REASON ────────────────────────────────────

        # For each stored observation that is blank (no value was ever present),
        # a missing-reason explanation is required.
        _metric_reasons: list[tuple[str, MetricObservation, str | None]] = [
            ("cpu", cpu_obs, cpu_missing_reason),
            ("ram", ram_obs, ram_missing_reason),
            ("storage", storage_obs, storage_missing_reason),
            ("network", network_obs, network_missing_reason),
        ]
        for field_name, obs, reason in _metric_reasons:
            if (
                obs.parse_outcome == ObservationOutcome.BLANK
                and not reason
            ):
                findings.append(
                    LineageFinding(
                        finding_type=LineageFindingType.MISSING_METRIC_REASON,
                        field_name=field_name,
                        detail=(
                            f"Metric '{field_name}' is blank but no "
                            f"missing-reason was provided.  Supply a reason "
                            f"(e.g. 'Monitoring agent not installed') or "
                            f"populate the measurement."
                        ),
                    )
                )

        # ── 4c: DERIVED_UNVERIFIED ───────────────────────────────────────

        # When algorithm_version is unknown and at least one stored observation
        # has a successfully parsed value, generate one finding per affected
        # field so each gap is individually addressable.
        if algorithm_version is None:
            for field_name, obs in [
                ("cpu", cpu_obs),
                ("ram", ram_obs),
                ("storage", storage_obs),
                ("network", network_obs),
            ]:
                if obs.parsed_value is not None:
                    findings.append(
                        LineageFinding(
                            finding_type=LineageFindingType.DERIVED_UNVERIFIED,
                            field_name=field_name,
                            detail=(
                                f"Metric '{field_name}' has a parsed value but "
                                f"no algorithm or workbook version was supplied.  "
                                f"The observation cannot satisfy sizing approval "
                                f"without verified derivation provenance."
                            ),
                        )
                    )

        return cls(
            server_name=server_name,
            cpu_observation=cpu_obs,
            ram_observation=ram_obs,
            storage_observation=storage_obs,
            network_observation=network_obs,
            measurement_window=measurement_window,
            findings=tuple(findings),
        )


# ---------------------------------------------------------------------------
# Public parsing helper
# ---------------------------------------------------------------------------


def parse_metric_observation(
    raw_text: str | None,
    field_name: str,
) -> MetricObservation:
    """Parse a raw cell value into a :class:`MetricObservation`.

    This function handles only the text-to-Decimal parsing stage.  It does
    not apply measurement-window context or algorithm-version provenance;
    those are applied by :meth:`WaveUtilRowLineage.from_raw`.

    Rules
    -----
    - ``None`` or blank/whitespace-only string → ``BLANK``, no parsed value.
    - Cached Excel error (``#VALUE!``, ``#DIV/0!``, etc.) → ``CACHED_ERROR``.
    - Negative, NaN, infinity, or locale-ambiguous comma → ``INVALID``.
    - Valid non-negative finite decimal → ``PARSED_OK``, value set.

    Parameters
    ----------
    raw_text:
        Raw cell text from the spreadsheet, or ``None`` for a missing cell.
    field_name:
        Canonical field name; used in ``parse_decimal`` error messages.

    Returns
    -------
    MetricObservation
        Parsed observation with ``algorithm_version=None`` (the caller is
        responsible for setting this in context).
    """
    # Normalise None to empty string for consistent raw_text storage.
    text: str = raw_text if raw_text is not None else ""

    stripped = text.strip()

    # ── BLANK ─────────────────────────────────────────────────────────────
    if not stripped:
        return MetricObservation(
            raw_text=text,
            parsed_value=None,
            parse_outcome=ObservationOutcome.BLANK,
        )

    # ── CACHED_ERROR ───────────────────────────────────────────────────────
    if is_excel_cached_error(stripped):
        return MetricObservation(
            raw_text=text,
            parsed_value=None,
            parse_outcome=ObservationOutcome.CACHED_ERROR,
        )

    # ── PARSED_OK or INVALID ───────────────────────────────────────────────
    # Delegate to parse_decimal which rejects negatives, NaN, infinity, and
    # locale-ambiguous comma separators with WaveUtilParseError.
    try:
        parsed = parse_decimal(stripped, field_name)
    except WaveUtilParseError:
        return MetricObservation(
            raw_text=text,
            parsed_value=None,
            parse_outcome=ObservationOutcome.INVALID,
        )

    # parse_decimal returns None for blank input; that case is already
    # handled above, so parsed is a Decimal here.
    assert parsed is not None, (
        f"parse_decimal returned None for non-blank input {stripped!r}; "
        f"this is a programming error in parse_metric_observation."
    )

    return MetricObservation(
        raw_text=text,
        parsed_value=parsed,
        parse_outcome=ObservationOutcome.PARSED_OK,
    )
