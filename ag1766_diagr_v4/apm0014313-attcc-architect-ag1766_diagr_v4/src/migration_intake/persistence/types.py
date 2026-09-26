"""
Portable SQLAlchemy column type definitions.

Every type in this module must behave identically on SQLite and Oracle
(and any future dialect).  The goal is that application code works with
native Python objects (``uuid.UUID``, ``datetime``, ``Decimal``, ``dict``,
``str``) without caring about the physical storage representation.

Design decisions (from Architecture sections 33 and 34):
- UUIDs: CHAR(36) canonical string, generated in application code.
- Timestamps: ISO text with UTC normalisation; always timezone-aware on read.
- Decimal: ``Numeric(precision, scale)`` with Python ``Decimal``; floats rejected.
- JSON: canonical UTF-8 text with sorted keys; no database-native JSON.
- SHA-256: lowercase 64-char hexadecimal, length-validated on bind.

Adding new types:
- Extend ``TypeDecorator`` with ``cache_ok = True``.
- Implement ``process_bind_param`` (Python → DB) and
  ``process_result_value`` (DB → Python).
- Add a matching contract test in ``tests/contract/persistence/test_portable_types.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, String, Text
from sqlalchemy.types import TypeDecorator

# ---------------------------------------------------------------------------
# PortableUUID
# ---------------------------------------------------------------------------


class PortableUUID(TypeDecorator):
    """
    UUID stored as a 36-character canonical hyphenated string (CHAR(36)).

    Application code passes and receives ``uuid.UUID`` objects.  The database
    stores the lowercase hyphenated string representation, which is readable,
    portable, and identical across SQLite and Oracle.

    String input is validated and normalised via ``uuid.UUID(value)``.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        """Convert uuid.UUID or str → canonical UUID string for storage."""
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, str):
            return str(uuid.UUID(value))  # validates and normalises
        raise TypeError(
            f"PortableUUID expects uuid.UUID or str, got {type(value).__name__}"
        )

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        """Convert stored string → uuid.UUID."""
        if value is None:
            return None
        return uuid.UUID(str(value))


# ---------------------------------------------------------------------------
# PortableUTC
# ---------------------------------------------------------------------------


class PortableUTC(TypeDecorator):
    """
    Timezone-aware UTC timestamp stored as ISO 8601 text.

    Application code always passes and receives timezone-aware ``datetime``
    objects.  Naive datetimes are rejected to avoid silent timezone bugs.
    Non-UTC input is converted to UTC before storage.

    SQLite stores as an ISO text string; the type restores ``timezone.utc``
    on read regardless of whether the stored string carries ``+00:00``.

    Oracle support requires a timestamp column that accepts ISO strings or
    explicit binding; this will be verified in Oracle contract tests.
    """

    impl = String(32)  # ISO UTC format fits within 32 chars
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        """Convert aware datetime → UTC ISO string for storage."""
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(
                f"PortableUTC expects a datetime object, got {type(value).__name__}"
            )
        if value.tzinfo is None:
            raise ValueError(
                "PortableUTC does not accept naive datetimes; "
                "supply a UTC-aware datetime (e.g. datetime.now(timezone.utc))"
            )
        return value.astimezone(UTC).isoformat()

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        """Convert stored ISO string → UTC-aware datetime."""
        if value is None:
            return None
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            # SQLite stored without offset; treat as UTC
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# PortableDecimal
# ---------------------------------------------------------------------------


class PortableDecimal(TypeDecorator):
    """
    Decimal measurement stored with explicit precision and scale.

    Wraps SQLAlchemy ``Numeric`` and enforces ``Decimal`` in application code.
    Float values are explicitly rejected to prevent silent precision loss in
    canonical measurement data.

    Usage::

        Column(PortableDecimal(precision=18, scale=6))
    """

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int, **kwargs: Any) -> None:
        super().__init__(precision=precision, scale=scale, **kwargs)

    def process_bind_param(self, value: Any, dialect: Any) -> Decimal | None:
        """Convert Python value → Decimal for storage (floats rejected)."""
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError(
                "Float values must not be used for canonical measurements; "
                "convert to Decimal before passing to PortableDecimal"
            )
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, str)):
            return Decimal(str(value))
        raise TypeError(
            f"PortableDecimal expects Decimal, int, or str; got {type(value).__name__}"
        )

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        """Convert stored numeric value → Python Decimal."""
        if value is None:
            return None
        return Decimal(str(value))


# ---------------------------------------------------------------------------
# CanonicalJSON
# ---------------------------------------------------------------------------


class CanonicalJSON(TypeDecorator):
    """
    Structured payload stored as canonical UTF-8 JSON text.

    Keys are sorted for deterministic representation, which aids diffing and
    hashing of payloads.  Database-native JSON types are deliberately avoided
    to ensure identical portability across SQLite and Oracle.

    Application code passes and receives Python dicts/lists.  The physical
    value is always a plain text string in the database.

    Note: frequently filtered fields (e.g. question_id, state) must be stored
    as separate relational columns, not inside a JSON payload.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        """Serialize Python object → canonical JSON text."""
        if value is None:
            return None
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    def process_result_value(self, value: Any, dialect: Any) -> Any | None:
        """Deserialize stored JSON text → Python object."""
        if value is None:
            return None
        return json.loads(str(value))


# ---------------------------------------------------------------------------
# Sha256Hex
# ---------------------------------------------------------------------------

_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdef")
_SHA256_HEX_LENGTH: int = 64


class Sha256Hex(TypeDecorator):
    """
    SHA-256 digest stored as lowercase 64-character hexadecimal text.

    Enforces:
    - Exactly 64 hexadecimal characters.
    - Lowercase normalisation (uppercase input is accepted and lowercased).
    - Only 0-9, a-f characters.

    Application code should generate hashes with ``hashlib.sha256(data).hexdigest()``.
    """

    impl = String(_SHA256_HEX_LENGTH)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        """Validate and normalise SHA-256 hex string for storage."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(
                f"Sha256Hex expects a str, got {type(value).__name__}"
            )
        normalised = value.lower()
        if len(normalised) != _SHA256_HEX_LENGTH:
            raise ValueError(
                f"SHA-256 hex must be exactly {_SHA256_HEX_LENGTH} characters; "
                f"got {len(normalised)}"
            )
        invalid = set(normalised) - _HEX_CHARS
        if invalid:
            raise ValueError(
                f"SHA-256 hex contains non-hexadecimal characters: {sorted(invalid)}"
            )
        return normalised

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        """Retrieve and normalise stored hex string."""
        if value is None:
            return None
        return str(value).lower()
