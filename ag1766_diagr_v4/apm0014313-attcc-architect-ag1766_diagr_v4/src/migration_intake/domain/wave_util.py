"""
WaveUtil canonical value model (V01).

Defines typed field groups and parsing rules for WaveUtil register rows.
All decimal values use Python Decimal, not float.
No SQLAlchemy or Pydantic dependencies in the domain layer.

Architecture references: sections 17–18.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

# ---------------------------------------------------------------------------
# Internal patterns
# ---------------------------------------------------------------------------

#: Cached Excel formula-error pattern: starts with '#', followed by
#: uppercase letters, digits, '/', '!', or '?'.
#: Examples: #DIV/0!, #VALUE!, #REF!, #NAME?, #NUM!, #N/A, #NULL!
_EXCEL_CACHED_ERROR_RE: re.Pattern[str] = re.compile(r"^#[A-Z0-9/!?]+$")

#: CLLI (Common Language Location Identifier) pattern.
#: Typically 8–11 uppercase alphanumeric characters.
_CLLI_RE: re.Pattern[str] = re.compile(r"^[A-Z0-9]{8,11}$")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class BusinessCriticality(str, Enum):
    """Approved vocabulary for business criticality (G0 decision APP-004)."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class ApplicationEnvironment(str, Enum):
    """Canonical environment codes mapped from 'Server Type' raw values."""

    PRODUCTION = "PRODUCTION"
    TEST = "TEST"
    DEVELOPMENT = "DEVELOPMENT"
    DR = "DR"
    STAGING = "STAGING"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def normalize(cls, raw: str) -> ApplicationEnvironment:
        """Map common raw Server Type values to canonical environment codes.

        Parameters
        ----------
        raw:
            Raw cell value from the 'Server Type' column.

        Returns
        -------
        ApplicationEnvironment
            Canonical code, or UNKNOWN if the raw value is not recognised.
        """
        _mapping: dict[str, ApplicationEnvironment] = {
            "production": cls.PRODUCTION,
            "prod": cls.PRODUCTION,
            "test": cls.TEST,
            "testing": cls.TEST,
            "qa": cls.TEST,
            "dev": cls.DEVELOPMENT,
            "development": cls.DEVELOPMENT,
            "dr": cls.DR,
            "disaster recovery": cls.DR,
            "staging": cls.STAGING,
            "stage": cls.STAGING,
        }
        return _mapping.get(raw.lower().strip(), cls.UNKNOWN)


class DerivationState(str, Enum):
    """Provenance state for recommendation fields."""

    FORMULA_VERIFIED = "FORMULA_VERIFIED"
    DERIVED_UNVERIFIED = "DERIVED_UNVERIFIED"
    OBSERVED = "OBSERVED"
    MISSING = "MISSING"


# ---------------------------------------------------------------------------
# Typed field-group dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaveUtilIdentityFields:
    """Application and source-identity fields from a WaveUtil row.

    Attributes
    ----------
    server_name:
        Required; normalised from the raw 'Server Name' column.
    mots_id:
        MOTS application identifier; None when blank.
    application_name:
        Free-text application name; None when blank.
    source_hosting_platform:
        Raw + normalised value from the 'Environment' column.
        NOTE: 'Environment' is semantically misleading; it describes the
        current hosting platform, not an environment type.
    source_environment_type_raw:
        Raw value from 'Environment Type'; preserved as text.
    application_environment:
        Canonical enum derived from 'Server Type' raw value.
    source_data_center:
        Current data centre name from 'Current - Data Center'.
    target_clli:
        Split from 'Target Data Center' when the value is a valid CLLI code.
    target_disposition:
        Split from 'Target Data Center' when the value is disposition text.
    business_criticality:
        Canonical criticality from the approved APP-004 vocabulary.
    application_lifecycle:
        Raw lifecycle status text; None when blank.
    """

    server_name: str
    mots_id: str | None
    application_name: str | None
    source_hosting_platform: str | None
    source_environment_type_raw: str | None
    application_environment: ApplicationEnvironment
    source_data_center: str | None
    target_clli: str | None
    target_disposition: str | None
    business_criticality: BusinessCriticality
    application_lifecycle: str | None


@dataclass(frozen=True)
class WaveUtilInventoryFields:
    """Technical inventory fields from a WaveUtil row.

    ``os_version`` is *always* stored as text and never coerced to a
    numeric type, even when its raw value looks like a number (e.g. "8.1").
    """

    operating_system: str | None
    os_version: str | None          # ALWAYS text — never numeric
    serial_number: str | None
    cpu_allocated: Decimal | None
    cpu_cores: Decimal | None
    memory_allocated_gb: Decimal | None
    storage_allocated_gb: Decimal | None
    virtual_disk_count_or_raw: str | None   # integer string or raw/error text
    nic_count_or_raw: str | None            # integer string or raw/error text


@dataclass(frozen=True)
class WaveUtilObservationFields:
    """Observed utilisation percentile and max measurements."""

    cpu_p95_percent: Decimal | None
    cpu_max_percent: Decimal | None
    memory_p95_gb: Decimal | None
    memory_max_gb: Decimal | None
    disk_p95_gb: Decimal | None
    disk_max_gb: Decimal | None


@dataclass(frozen=True)
class WaveUtilRecommendationFields:
    """Derived sizing recommendation fields."""

    recommended_vcpu: Decimal | None
    recommended_memory_gb: Decimal | None
    source_exception_flag: str | None
    recommended_instance_type: str | None
    final_allocated_vcpu: Decimal | None
    final_allocated_memory_gb: Decimal | None
    recommended_ebs_gb: Decimal | None
    recommended_target_dc: str | None
    derivation_state: DerivationState = DerivationState.DERIVED_UNVERIFIED


@dataclass(frozen=True)
class WaveUtilRowValues:
    """All parsed field groups for one WaveUtil row."""

    identity: WaveUtilIdentityFields
    inventory: WaveUtilInventoryFields
    observations: WaveUtilObservationFields
    recommendations: WaveUtilRecommendationFields


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class WaveUtilParseError(Exception):
    """Raised when a field value violates WaveUtil parsing rules."""


# ---------------------------------------------------------------------------
# Public parsing helpers
# ---------------------------------------------------------------------------


def is_excel_cached_error(value: str) -> bool:
    """Return True if *value* looks like a cached Excel formula error.

    Recognised patterns: ``#DIV/0!``, ``#VALUE!``, ``#REF!``, ``#NAME?``,
    ``#NUM!``, ``#N/A``, ``#NULL!``.

    Parameters
    ----------
    value:
        String to inspect.  Leading/trailing whitespace is stripped before
        matching.

    Returns
    -------
    bool
        ``True`` if the value matches the Excel cached-error pattern.
    """
    return bool(_EXCEL_CACHED_ERROR_RE.match(value.strip()))


def parse_decimal(value: str | None, field_name: str) -> Decimal | None:
    """Parse a measurement field into a ``Decimal``.

    Rules
    -----
    - ``None`` or blank string → returns ``None`` (not zero).
    - Negative values → raises :exc:`WaveUtilParseError`.
    - ``NaN`` (any case) → raises :exc:`WaveUtilParseError`.
    - Infinity (any variant) → raises :exc:`WaveUtilParseError`.
    - Values containing a comma → raises :exc:`WaveUtilParseError`
      (ambiguous locale; caller must supply plain decimal notation such
      as ``'1234.56'`` rather than ``'1,234.56'``).
    - Cached Excel errors (e.g. ``#DIV/0!``) → raises
      :exc:`WaveUtilParseError`.
    - Values that cannot be parsed by ``Decimal()`` → raises
      :exc:`WaveUtilParseError`.

    Parameters
    ----------
    value:
        Raw string from a sheet cell, or ``None``.
    field_name:
        Canonical field name used in error messages.

    Returns
    -------
    Decimal | None
        Parsed non-negative finite decimal value, or ``None`` when blank.

    Raises
    ------
    WaveUtilParseError
        For any rule violation listed above.
    """
    if value is None:
        return None

    s = value.strip()
    if not s:
        return None

    # Reject cached Excel errors early
    if is_excel_cached_error(s):
        raise WaveUtilParseError(
            f"Field {field_name!r}: Excel cached error {s!r} is not a valid decimal value. "
            f"Correct the source data before ingestion."
        )

    # Reject locale-ambiguous values (comma as thousands or decimal separator)
    if "," in s:
        raise WaveUtilParseError(
            f"Field {field_name!r}: Value {s!r} contains a comma, which is ambiguous "
            f"(locale-dependent). Use plain decimal notation, e.g. '1234.56'."
        )

    # Attempt Decimal conversion
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise WaveUtilParseError(
            f"Field {field_name!r}: Cannot parse {s!r} as a decimal number."
        ) from None

    # Reject NaN
    if d.is_nan():
        raise WaveUtilParseError(
            f"Field {field_name!r}: NaN is not a valid measurement value. "
            f"Blank the cell instead of using NaN."
        )

    # Reject infinity
    if d.is_infinite():
        raise WaveUtilParseError(
            f"Field {field_name!r}: Infinity is not a valid measurement value. "
            f"Raw input was {s!r}."
        )

    # Reject negative
    if d < 0:
        raise WaveUtilParseError(
            f"Field {field_name!r}: Negative value {s!r} is not valid for a "
            f"measurement field.  All capacity and utilisation values must be "
            f"zero or positive."
        )

    return d


def parse_business_criticality(raw: str | None) -> BusinessCriticality:
    """Map raw text to a :class:`BusinessCriticality` enum value.

    Matching is case-insensitive.  Returns ``UNKNOWN`` for blank input or
    any value not in the approved vocabulary.

    Parameters
    ----------
    raw:
        Raw string from the 'Business Criticality' column, or ``None``.

    Returns
    -------
    BusinessCriticality
        Canonical criticality code; ``UNKNOWN`` when unmapped.
    """
    if raw is None or not raw.strip():
        return BusinessCriticality.UNKNOWN

    normalised = raw.strip().upper()
    try:
        return BusinessCriticality(normalised)
    except ValueError:
        return BusinessCriticality.UNKNOWN


def split_target_data_center(
    raw: str | None,
) -> tuple[str | None, str | None]:
    """Split a 'Target Data Center' raw value into CLLI and disposition parts.

    A valid CLLI code is 8–11 uppercase alphanumeric characters
    (``[A-Z0-9]{8,11}``).  Any value that does not match this pattern is
    treated as disposition text (e.g. ``'Decommission'``, ``'Not Found'``,
    ``'TBD'``).

    Parameters
    ----------
    raw:
        Raw cell value from 'Target Data Center', or ``None``.

    Returns
    -------
    tuple[str | None, str | None]
        ``(target_clli, target_disposition)``.  At most one element is
        non-``None``; both are ``None`` when *raw* is blank.
    """
    if raw is None:
        return (None, None)

    s = raw.strip()
    if not s:
        return (None, None)

    if _CLLI_RE.match(s):
        return (s, None)

    return (None, s)
