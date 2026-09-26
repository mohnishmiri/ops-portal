"""
Value objects for domain validation and normalization.

Value objects are immutable and validate their contents on creation.
They have no identity and are compared by value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class NormalizedName:
    """
    Normalized application/entity name.

    Normalizes by:
    - Stripping leading/trailing whitespace
    - Collapsing internal whitespace to single spaces
    - Preserving case
    """

    value: str

    def __init__(self, value: str) -> None:
        if value is None:
            raise ValueError("Name cannot be None")

        # Normalize whitespace
        normalized = " ".join(value.split())

        if not normalized:
            raise ValueError("Name cannot be empty")

        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class NormalizedAcronym:
    """
    Normalized acronym (uppercase, stripped).

    Normalizes by:
    - Stripping whitespace
    - Converting to uppercase
    """

    value: str

    def __init__(self, value: str) -> None:
        if value is None:
            raise ValueError("Acronym cannot be None")

        normalized = value.strip().upper()

        if not normalized:
            raise ValueError("Acronym cannot be empty")

        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_optional(cls, value: str | None) -> NormalizedAcronym | None:
        """Create from optional value, returning None if input is None or empty."""
        if value is None or not value.strip():
            return None
        return cls(value)


@dataclass(frozen=True, slots=True)
class SafeDecimal:
    """
    Decimal value that rejects NaN and Infinity.

    Used for numeric values that must be finite and valid.
    """

    value: Decimal

    def __init__(self, value: Decimal | int | str) -> None:
        if isinstance(value, Decimal):
            decimal_value = value
        elif isinstance(value, (int, str)):
            try:
                decimal_value = Decimal(value)
            except InvalidOperation as e:
                raise ValueError(f"Invalid decimal value: {value}") from e
        else:
            raise TypeError(f"Expected Decimal, int, or str, got {type(value)}")

        if decimal_value.is_nan():
            raise ValueError("NaN is not allowed")

        if decimal_value.is_infinite():
            raise ValueError("Infinity is not allowed")

        object.__setattr__(self, "value", decimal_value)

    def __str__(self) -> str:
        return str(self.value)

    def __float__(self) -> float:
        return float(self.value)

    def __int__(self) -> int:
        return int(self.value)


@dataclass(frozen=True, slots=True)
class UtcTimestamp:
    """
    UTC timestamp that ensures timezone awareness.

    All timestamps in the domain must be UTC. Non-UTC timestamps
    are converted to UTC on creation.
    """

    value: datetime

    def __init__(self, value: datetime) -> None:
        if value is None:
            raise ValueError("Timestamp cannot be None")

        if value.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (UTC required)")

        # Convert to UTC if not already
        utc_value = value.astimezone(UTC)

        object.__setattr__(self, "value", utc_value)

    def __str__(self) -> str:
        return self.value.isoformat()

    @classmethod
    def now(cls) -> UtcTimestamp:
        """Create a timestamp for the current UTC time."""
        return cls(datetime.now(UTC))

    def to_iso(self) -> str:
        """Return ISO 8601 formatted string."""
        return self.value.isoformat()


@dataclass(frozen=True, slots=True)
class VersionToken:
    """
    Optimistic concurrency version token.

    Used for optimistic locking to detect concurrent modifications.
    """

    value: int

    def __init__(self, value: int) -> None:
        if value < 0:
            raise ValueError("Version must be non-negative")

        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return str(self.value)

    def next(self) -> VersionToken:
        """Return the next version token."""
        return VersionToken(self.value + 1)

    @classmethod
    def initial(cls) -> VersionToken:
        """Return the initial version token (1)."""
        return cls(1)


# Pattern for control codes: PREFIX-NNN (e.g., APP-001, CTL-002)
CONTROL_CODE_PATTERN = re.compile(r"^[A-Z]{2,5}-\d{3}$")


@dataclass(frozen=True, slots=True)
class ControlCode:
    """
    Normalized control code (e.g., APP-001, CTL-002).

    Format: 2-5 uppercase letters, hyphen, 3 digits.
    """

    value: str

    def __init__(self, value: str) -> None:
        if value is None:
            raise ValueError("Control code cannot be None")

        normalized = value.strip().upper()

        if not normalized:
            raise ValueError("Control code cannot be empty")

        if not CONTROL_CODE_PATTERN.match(normalized):
            raise ValueError(
                f"Invalid control code format: {value}. "
                "Expected format: PREFIX-NNN (e.g., APP-001)"
            )

        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    @property
    def prefix(self) -> str:
        """Return the prefix part (e.g., 'APP' from 'APP-001')."""
        return self.value.split("-")[0]

    @property
    def number(self) -> int:
        """Return the numeric part (e.g., 1 from 'APP-001')."""
        return int(self.value.split("-")[1])


@dataclass(frozen=True, slots=True)
class StorageKey:
    """
    Content-addressed storage key for evidence files.

    Typically a hash-based key that identifies file content.
    """

    value: str

    def __init__(self, value: str) -> None:
        if value is None:
            raise ValueError("Storage key cannot be None")

        normalized = value.strip()

        if not normalized:
            raise ValueError("Storage key cannot be empty")

        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ContentHash:
    """
    SHA-256 hash of file content.

    Used for content-addressed storage and integrity verification.
    """

    value: str
    algorithm: str = "sha256"

    def __init__(self, value: str, algorithm: str = "sha256") -> None:
        if value is None:
            raise ValueError("Content hash cannot be None")

        normalized = value.strip().lower()

        if not normalized:
            raise ValueError("Content hash cannot be empty")

        # Validate hex format for SHA-256 (64 characters)
        if algorithm == "sha256" and len(normalized) != 64:
            raise ValueError(
                f"Invalid SHA-256 hash length: {len(normalized)}, expected 64"
            )

        if not all(c in "0123456789abcdef" for c in normalized):
            raise ValueError("Content hash must be hexadecimal")

        object.__setattr__(self, "value", normalized)
        object.__setattr__(self, "algorithm", algorithm)

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.value}"
