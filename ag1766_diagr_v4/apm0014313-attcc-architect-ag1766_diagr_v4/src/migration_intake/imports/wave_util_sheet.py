"""
WaveUtil sheet header contract and row parser (V01).

Architecture references: sections 17–18.

Design invariants
-----------------
- ``WAVEUTIL_HEADERS`` maps every known raw column header (including
  the known-typo alias ``'Instantace Type'`` and the trailing-space
  variant ``'Server Name '``) to its canonical field name.
- ``WaveUtilSheetAdapter.validate_headers`` uses an *exact-match-only*
  lookup against ``WAVEUTIL_HEADERS``; no fuzzy matching is performed.
- ``WaveUtilSheetAdapter.parse_row`` accepts a dict keyed by *canonical*
  field names and returns a ``WaveUtilRowResult``.
- Blank cells produce no value (not zero, not "NO", not "unknown").
- Cached Excel errors in integer-or-raw fields produce a
  ``CACHED_ERROR`` finding and ``None`` — never zero.
- Negative, NaN, and Infinity decimal values produce an
  ``INVALID_DECIMAL`` finding and ``None``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from migration_intake.domain.wave_util import (
    ApplicationEnvironment,
    DerivationState,
    WaveUtilIdentityFields,
    WaveUtilInventoryFields,
    WaveUtilObservationFields,
    WaveUtilParseError,
    WaveUtilRecommendationFields,
    WaveUtilRowValues,
    is_excel_cached_error,
    parse_business_criticality,
    parse_decimal,
    split_target_data_center,
)

# ---------------------------------------------------------------------------
# Header contract
# ---------------------------------------------------------------------------

#: Canonical mapping of all 34 known WaveUtil column headers to their
#: canonical domain field names.  Two variants of "Server Name" are included
#: because a trailing space is a known data-quality quirk in source workbooks.
#: "Instantace Type" (with typo) is a known alias per architecture section 18.2.
WAVEUTIL_HEADERS: dict[str, str] = {
    # Application and source identity
    "Server Name ": "server_name",          # NOTE: trailing space is a known variant
    "Server Name": "server_name",
    "Mots Id": "mots_id",
    "Application": "application_name",
    "Environment": "source_hosting_platform",       # semantically misleading header
    "Environment Type": "source_environment_type_raw",
    "Server Type": "application_environment",       # maps to canonical env codes
    "Current - Data Center": "source_data_center",
    "Target Data Center": "target_raw",             # split → target_clli / target_disposition
    "Business Criticality": "business_criticality",
    "App Life Cycle Status": "application_lifecycle",
    # Technical inventory
    "Server OS": "operating_system",
    "OS Version": "os_version",
    "Serial Number": "serial_number",
    "CPU Alloc": "cpu_allocated",
    "CPU Core": "cpu_cores",
    "RAM Alloc (GB)": "memory_allocated_gb",
    "Storage Alloc (GB)": "storage_allocated_gb",
    "Virtual Disk": "virtual_disk_count_or_raw",
    "NIC": "nic_count_or_raw",
    # Observed utilisation
    "CPU 95%ile Usage (%)": "cpu_p95_percent",
    "CPU Max Usage (%)": "cpu_max_percent",
    "Memory 95%ile Usage (GB)": "memory_p95_gb",
    "Memory MAX Usage (GB)": "memory_max_gb",
    "Disk Space Utilization 95%ile (GB)": "disk_p95_gb",
    "Disk Space Utilization Max (GB)": "disk_max_gb",
    # Derived recommendations
    "vCPU Optimized": "recommended_vcpu",
    "Memory Optimized": "recommended_memory_gb",
    "Is Exception": "source_exception_flag",
    "Instantace Type": "recommended_instance_type",     # known typo alias
    "Allocated vCPU_final": "final_allocated_vcpu",
    "Allocated memory_final": "final_allocated_memory_gb",
    "Allocated Storage (EBS) in GB 25% Increase": "recommended_ebs_gb",
    "Target DC": "recommended_target_dc",
}


# ---------------------------------------------------------------------------
# Finding types
# ---------------------------------------------------------------------------


class WaveUtilFindingType(str, Enum):
    """Categories of structural or semantic anomalies found during parsing."""

    MISSING_HEADER = "MISSING_HEADER"
    UNKNOWN_HEADER = "UNKNOWN_HEADER"
    INVALID_DECIMAL = "INVALID_DECIMAL"
    CACHED_ERROR = "CACHED_ERROR"
    MISSING_SERVER_NAME = "MISSING_SERVER_NAME"
    INVALID_CRITICALITY = "INVALID_CRITICALITY"


# ---------------------------------------------------------------------------
# Result and finding dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaveUtilFinding:
    """One anomaly finding attached to a row parse result.

    Attributes
    ----------
    row_number:
        1-based row number in the source sheet.
    finding_type:
        Category of the finding.
    field_name:
        Canonical field name where the issue was detected.
    raw_value:
        Original cell value as read from the sheet.
    detail:
        Human-readable explanation of the anomaly.
    """

    row_number: int
    finding_type: WaveUtilFindingType
    field_name: str
    raw_value: str
    detail: str


@dataclass(frozen=True)
class WaveUtilRowResult:
    """Immutable result of parsing one WaveUtil data row.

    Attributes
    ----------
    row_number:
        1-based row number in the source sheet.
    values:
        Fully typed field groups when the row is valid; ``None`` when the
        row is invalid (e.g. missing ``server_name``).
    findings:
        Tuple of all anomaly findings for this row.
    """

    row_number: int
    values: WaveUtilRowValues | None
    findings: tuple[WaveUtilFinding, ...]


@dataclass(frozen=True)
class WaveUtilSheetResult:
    """Immutable summary of a complete WaveUtil sheet parse.

    Attributes
    ----------
    outcome:
        ``'VALID'`` when all required headers are present; ``'INVALID'``
        otherwise.
    headers_found:
        Canonical field names for each header that was recognised.
    missing_required_headers:
        Canonical names of required headers absent from the sheet.
    unknown_headers:
        Raw header strings that did not map to any canonical field name.
    row_results:
        One result per data row parsed.
    """

    outcome: str
    headers_found: tuple[str, ...]
    missing_required_headers: tuple[str, ...]
    unknown_headers: tuple[str, ...]
    row_results: tuple[WaveUtilRowResult, ...]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class WaveUtilSheetAdapter:
    """Validates WaveUtil headers and parses each row into typed values.

    Usage
    -----
    1. Call :meth:`validate_headers` with the raw header row to get the
       canonical names, missing required headers, and unknown headers.
    2. For each data row, map raw column values to a ``dict`` keyed by
       canonical field names, then call :meth:`parse_row`.
    """

    #: Canonical names of headers that *must* be present for parsing to
    #: produce useful output.  Absence is reported as a MISSING_HEADER finding
    #: but does not prevent the adapter from attempting to parse rows.
    REQUIRED_HEADERS: frozenset[str] = frozenset(
        {"server_name", "mots_id", "application_name"}
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_headers(
        self, raw_headers: list[str]
    ) -> tuple[list[str], list[str], list[str]]:
        """Resolve raw header strings to canonical field names.

        Lookup is *exact-match-only* against ``WAVEUTIL_HEADERS``.
        The known-typo alias ``'Instantace Type'`` and the trailing-space
        variant ``'Server Name '`` are already present as explicit keys, so
        no special normalisation is required beyond the dict lookup.

        Parameters
        ----------
        raw_headers:
            List of raw header strings as read from the first row of the
            WaveUtil sheet.

        Returns
        -------
        tuple[list[str], list[str], list[str]]
            ``(canonical_headers, missing_required, unknown_headers)`` where:

            - ``canonical_headers`` — canonical field name for every raw
              header that was recognised (preserves order; may contain
              duplicates when both ``'Server Name'`` and ``'Server Name '``
              appear).
            - ``missing_required`` — canonical names of :attr:`REQUIRED_HEADERS`
              that were absent from the recognised set.
            - ``unknown_headers`` — raw header strings that did not match
              any key in ``WAVEUTIL_HEADERS``.
        """
        canonical_headers: list[str] = []
        unknown_headers: list[str] = []

        for raw_header in raw_headers:
            canonical = WAVEUTIL_HEADERS.get(raw_header)
            if canonical is not None:
                canonical_headers.append(canonical)
            else:
                unknown_headers.append(raw_header)

        canonical_set = set(canonical_headers)
        missing_required = [
            req for req in sorted(self.REQUIRED_HEADERS)
            if req not in canonical_set
        ]

        return (canonical_headers, missing_required, unknown_headers)

    def parse_row(self, row: dict, row_number: int) -> WaveUtilRowResult:
        """Parse one data row dict into typed :class:`WaveUtilRowValues`.

        Parameters
        ----------
        row:
            Dictionary keyed by *canonical* field names (as returned by
            :meth:`validate_headers`) mapping to raw string cell values.
            Missing keys are treated identically to blank cells.
        row_number:
            1-based row number; stored on the result and each finding.

        Returns
        -------
        WaveUtilRowResult
            ``values`` is ``None`` when the row is invalid (e.g. blank
            ``server_name``); findings describe all anomalies detected.
        """
        findings: list[WaveUtilFinding] = []

        # ── Internal helpers ──────────────────────────────────────────

        def _get(field: str) -> str | None:
            """Return the stripped cell value, or None if blank/absent."""
            raw = row.get(field)
            if raw is None:
                return None
            s = str(raw).strip()
            return s if s else None

        def _decimal(field: str) -> Decimal | None:
            """Parse a decimal field; append a finding on error, return None."""
            raw = _get(field)
            if raw is None:
                return None
            try:
                return parse_decimal(raw, field)
            except WaveUtilParseError as exc:
                findings.append(
                    WaveUtilFinding(
                        row_number=row_number,
                        finding_type=WaveUtilFindingType.INVALID_DECIMAL,
                        field_name=field,
                        raw_value=raw,
                        detail=str(exc),
                    )
                )
                return None

        def _int_or_raw(field: str) -> str | None:
            """Return integer-or-raw field value.

            Cached Excel errors produce a CACHED_ERROR finding and return
            None — never zero.
            """
            raw = _get(field)
            if raw is None:
                return None
            if is_excel_cached_error(raw):
                findings.append(
                    WaveUtilFinding(
                        row_number=row_number,
                        finding_type=WaveUtilFindingType.CACHED_ERROR,
                        field_name=field,
                        raw_value=raw,
                        detail=(
                            f"Field {field!r} contains cached Excel error {raw!r}. "
                            f"The source formula must be resolved before ingestion."
                        ),
                    )
                )
                return None
            return raw

        # ── server_name is required ───────────────────────────────────

        server_name = _get("server_name")
        if not server_name:
            findings.append(
                WaveUtilFinding(
                    row_number=row_number,
                    finding_type=WaveUtilFindingType.MISSING_SERVER_NAME,
                    field_name="server_name",
                    raw_value=row.get("server_name") or "",
                    detail=(
                        f"Row {row_number}: 'server_name' is required but was "
                        f"blank or absent. Row cannot be parsed."
                    ),
                )
            )
            return WaveUtilRowResult(
                row_number=row_number,
                values=None,
                findings=tuple(findings),
            )

        # ── Identity fields ───────────────────────────────────────────

        target_raw = _get("target_raw")
        target_clli, target_disposition = split_target_data_center(target_raw)

        app_env_raw = _get("application_environment") or ""
        app_env = ApplicationEnvironment.normalize(app_env_raw)

        biz_crit = parse_business_criticality(_get("business_criticality"))

        identity = WaveUtilIdentityFields(
            server_name=server_name,
            mots_id=_get("mots_id"),
            application_name=_get("application_name"),
            source_hosting_platform=_get("source_hosting_platform"),
            source_environment_type_raw=_get("source_environment_type_raw"),
            application_environment=app_env,
            source_data_center=_get("source_data_center"),
            target_clli=target_clli,
            target_disposition=target_disposition,
            business_criticality=biz_crit,
            application_lifecycle=_get("application_lifecycle"),
        )

        # ── Inventory fields ──────────────────────────────────────────

        inventory = WaveUtilInventoryFields(
            operating_system=_get("operating_system"),
            os_version=_get("os_version"),             # always text, never numeric
            serial_number=_get("serial_number"),
            cpu_allocated=_decimal("cpu_allocated"),
            cpu_cores=_decimal("cpu_cores"),
            memory_allocated_gb=_decimal("memory_allocated_gb"),
            storage_allocated_gb=_decimal("storage_allocated_gb"),
            virtual_disk_count_or_raw=_int_or_raw("virtual_disk_count_or_raw"),
            nic_count_or_raw=_int_or_raw("nic_count_or_raw"),
        )

        # ── Observation fields ────────────────────────────────────────

        observations = WaveUtilObservationFields(
            cpu_p95_percent=_decimal("cpu_p95_percent"),
            cpu_max_percent=_decimal("cpu_max_percent"),
            memory_p95_gb=_decimal("memory_p95_gb"),
            memory_max_gb=_decimal("memory_max_gb"),
            disk_p95_gb=_decimal("disk_p95_gb"),
            disk_max_gb=_decimal("disk_max_gb"),
        )

        # ── Recommendation fields ─────────────────────────────────────

        recommendations = WaveUtilRecommendationFields(
            recommended_vcpu=_decimal("recommended_vcpu"),
            recommended_memory_gb=_decimal("recommended_memory_gb"),
            source_exception_flag=_get("source_exception_flag"),
            recommended_instance_type=_get("recommended_instance_type"),
            final_allocated_vcpu=_decimal("final_allocated_vcpu"),
            final_allocated_memory_gb=_decimal("final_allocated_memory_gb"),
            recommended_ebs_gb=_decimal("recommended_ebs_gb"),
            recommended_target_dc=_get("recommended_target_dc"),
            derivation_state=DerivationState.DERIVED_UNVERIFIED,
        )

        values = WaveUtilRowValues(
            identity=identity,
            inventory=inventory,
            observations=observations,
            recommendations=recommendations,
        )

        return WaveUtilRowResult(
            row_number=row_number,
            values=values,
            findings=tuple(findings),
        )
