"""
Contract tests for portable SQLAlchemy column types.

Each test exercises round-trip storage and retrieval for PortableUUID,
PortableUTC, PortableDecimal, CanonicalJSON, and Sha256Hex. All tests use
an in-memory SQLite engine with the standard pragma listener so they run
fast without side effects.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, String, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from migration_intake.persistence.database import (
    _configure_sqlite_connection,
    create_engine_from_url,
)
from migration_intake.persistence.types import (
    CanonicalJSON,
    PortableDecimal,
    PortableUTC,
    PortableUUID,
    Sha256Hex,
)


# ---------------------------------------------------------------------------
# ORM models used only within this test module
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _UUIDRow(_Base):
    __tablename__ = "_uuid_rows"
    id = Column(PortableUUID(), primary_key=True)
    ref = Column(PortableUUID(), nullable=True)


class _UTCRow(_Base):
    __tablename__ = "_utc_rows"
    id = Column(PortableUUID(), primary_key=True)
    created_at = Column(PortableUTC(), nullable=False)


class _DecimalRow(_Base):
    __tablename__ = "_decimal_rows"
    id = Column(PortableUUID(), primary_key=True)
    measurement = Column(PortableDecimal(precision=18, scale=6), nullable=True)


class _JSONRow(_Base):
    __tablename__ = "_json_rows"
    id = Column(PortableUUID(), primary_key=True)
    payload = Column(CanonicalJSON(), nullable=True)


class _HashRow(_Base):
    __tablename__ = "_hash_rows"
    id = Column(PortableUUID(), primary_key=True)
    digest = Column(Sha256Hex(), nullable=True)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine() -> Engine:
    """In-memory SQLite engine with all pragmas applied."""
    engine = create_engine_from_url(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    _Base.metadata.create_all(engine)
    yield engine
    _Base.metadata.drop_all(engine)
    engine.dispose()


def _uid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# PortableUUID
# ---------------------------------------------------------------------------


def test_uuid_round_trip(db_engine: Engine) -> None:
    """UUID stored and retrieved as uuid.UUID object."""
    pk = _uid()
    ref = _uid()
    with Session(db_engine) as s:
        s.add(_UUIDRow(id=pk, ref=ref))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_UUIDRow, pk)
        assert row.id == pk
        assert row.ref == ref
        assert isinstance(row.id, uuid.UUID)


def test_uuid_stored_as_string_in_database(db_engine: Engine) -> None:
    """UUID is stored as a plain string in the raw database row."""
    pk = _uid()
    with Session(db_engine) as s:
        s.add(_UUIDRow(id=pk))
        s.commit()
    with db_engine.connect() as conn:
        raw = conn.execute(text("SELECT id FROM _uuid_rows")).scalar()
    assert isinstance(raw, str)
    assert raw == str(pk)


def test_uuid_accepts_string_input(db_engine: Engine) -> None:
    """PortableUUID accepts a str input and round-trips as uuid.UUID."""
    str_pk = str(_uid())
    with Session(db_engine) as s:
        s.add(_UUIDRow(id=str_pk))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_UUIDRow, uuid.UUID(str_pk))
        assert str(row.id) == str_pk


def test_uuid_nullable_column_stores_none(db_engine: Engine) -> None:
    """Nullable UUID column stores and retrieves None correctly."""
    pk = _uid()
    with Session(db_engine) as s:
        s.add(_UUIDRow(id=pk, ref=None))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_UUIDRow, pk)
        assert row.ref is None


# ---------------------------------------------------------------------------
# PortableUTC
# ---------------------------------------------------------------------------


def test_utc_round_trip(db_engine: Engine) -> None:
    """UTC timestamp stored and retrieved as timezone-aware datetime."""
    pk = _uid()
    now = datetime.now(tz=timezone.utc)
    with Session(db_engine) as s:
        s.add(_UTCRow(id=pk, created_at=now))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_UTCRow, pk)
        assert row.created_at.tzinfo is not None
        diff = abs((row.created_at - now).total_seconds())
        assert diff < 0.001, f"Timestamp drift: {diff}s"


def test_utc_normalizes_non_utc_input(db_engine: Engine) -> None:
    """Non-UTC timezone input is converted and returned as UTC."""
    pk = _uid()
    eastern = timezone(timedelta(hours=-5))
    ts_input = datetime(2026, 6, 15, 10, 0, 0, tzinfo=eastern)
    expected_utc = datetime(2026, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
    with Session(db_engine) as s:
        s.add(_UTCRow(id=pk, created_at=ts_input))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_UTCRow, pk)
        actual = row.created_at.astimezone(timezone.utc)
        assert actual.replace(tzinfo=None) == expected_utc.replace(tzinfo=None)


def test_utc_rejects_naive_datetime(db_engine: Engine) -> None:
    """Naive datetime is rejected; all timestamps must be UTC-aware."""
    pk = _uid()
    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    with Session(db_engine) as s:
        s.add(_UTCRow(id=pk, created_at=naive))
        with pytest.raises(Exception):
            s.flush()


def test_utc_retrieved_value_is_utc_aware(db_engine: Engine) -> None:
    """Retrieved timestamp always carries UTC timezone info."""
    pk = _uid()
    now = datetime.now(tz=timezone.utc)
    with Session(db_engine) as s:
        s.add(_UTCRow(id=pk, created_at=now))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_UTCRow, pk)
        assert row.created_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# PortableDecimal
# ---------------------------------------------------------------------------


def test_decimal_round_trip(db_engine: Engine) -> None:
    """Decimal value stored and retrieved without floating-point loss."""
    pk = _uid()
    value = Decimal("123.456789")
    with Session(db_engine) as s:
        s.add(_DecimalRow(id=pk, measurement=value))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_DecimalRow, pk)
        assert row.measurement == value
        assert isinstance(row.measurement, Decimal)


def test_decimal_null_explicit(db_engine: Engine) -> None:
    """Null Decimal column stores and retrieves None."""
    pk = _uid()
    with Session(db_engine) as s:
        s.add(_DecimalRow(id=pk, measurement=None))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_DecimalRow, pk)
        assert row.measurement is None


def test_decimal_preserves_scale(db_engine: Engine) -> None:
    """Decimal preserves value equality for a trailing-zero quantity."""
    pk = _uid()
    value = Decimal("1.500000")
    with Session(db_engine) as s:
        s.add(_DecimalRow(id=pk, measurement=value))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_DecimalRow, pk)
        # Value equality (not necessarily same string repr after SQLite)
        assert row.measurement == value


def test_decimal_rejects_float_input(db_engine: Engine) -> None:
    """Float values must be rejected; application code must use Decimal.

    SQLAlchemy wraps the TypeError in a StatementError on flush; we check
    that the underlying cause is indeed the float-rejection TypeError.
    """
    from sqlalchemy.exc import StatementError

    pk = _uid()
    with Session(db_engine) as s:
        s.add(_DecimalRow(id=pk, measurement=3.14))  # type: ignore[arg-type]
        with pytest.raises((TypeError, StatementError)) as exc_info:
            s.flush()
    # Unwrap StatementError to confirm the root cause is our float guard
    exc = exc_info.value
    if isinstance(exc, StatementError):
        assert isinstance(exc.__cause__, TypeError)
        assert "Float" in str(exc.__cause__)
    else:
        assert "Float" in str(exc)


# ---------------------------------------------------------------------------
# CanonicalJSON
# ---------------------------------------------------------------------------


def test_json_round_trip(db_engine: Engine) -> None:
    """JSON dict payload stored and retrieved identically."""
    pk = _uid()
    payload = {"question": "APP-001", "value": True, "meta": {"source": "test"}}
    with Session(db_engine) as s:
        s.add(_JSONRow(id=pk, payload=payload))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_JSONRow, pk)
        assert row.payload == payload


def test_json_list_round_trip(db_engine: Engine) -> None:
    """JSON list payload round-trips correctly."""
    pk = _uid()
    payload = ["a", "b", "c", 1, 2, 3]
    with Session(db_engine) as s:
        s.add(_JSONRow(id=pk, payload=payload))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_JSONRow, pk)
        assert row.payload == payload


def test_json_null_explicit(db_engine: Engine) -> None:
    """Null JSON column stores and retrieves None."""
    pk = _uid()
    with Session(db_engine) as s:
        s.add(_JSONRow(id=pk, payload=None))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_JSONRow, pk)
        assert row.payload is None


def test_json_stores_as_text(db_engine: Engine) -> None:
    """JSON payload is physically stored as a text string."""
    pk = _uid()
    payload = {"k": "v"}
    with Session(db_engine) as s:
        s.add(_JSONRow(id=pk, payload=payload))
        s.commit()
    with db_engine.connect() as conn:
        raw = conn.execute(text("SELECT payload FROM _json_rows")).scalar()
    assert isinstance(raw, str)
    import json
    assert json.loads(raw) == payload


# ---------------------------------------------------------------------------
# Sha256Hex
# ---------------------------------------------------------------------------


def test_sha256_hex_round_trip(db_engine: Engine) -> None:
    """SHA-256 hex hash stored and retrieved as 64-char lowercase hex."""
    pk = _uid()
    digest = hashlib.sha256(b"test content").hexdigest()
    assert len(digest) == 64
    with Session(db_engine) as s:
        s.add(_HashRow(id=pk, digest=digest))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_HashRow, pk)
        assert row.digest == digest
        assert row.digest == row.digest.lower()


def test_sha256_hex_null_explicit(db_engine: Engine) -> None:
    """Null SHA-256 column stores and retrieves None."""
    pk = _uid()
    with Session(db_engine) as s:
        s.add(_HashRow(id=pk, digest=None))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_HashRow, pk)
        assert row.digest is None


def test_sha256_hex_rejects_wrong_length(db_engine: Engine) -> None:
    """SHA-256 hex value with wrong length is rejected on bind."""
    pk = _uid()
    with Session(db_engine) as s:
        s.add(_HashRow(id=pk, digest="abc123"))
        with pytest.raises((ValueError, Exception)):
            s.flush()


def test_sha256_hex_rejects_non_hex_characters(db_engine: Engine) -> None:
    """SHA-256 hex with non-hex characters is rejected."""
    pk = _uid()
    bad_hash = "g" * 64  # 'g' is not a hex character
    with Session(db_engine) as s:
        s.add(_HashRow(id=pk, digest=bad_hash))
        with pytest.raises((ValueError, Exception)):
            s.flush()


def test_sha256_hex_normalizes_to_lowercase(db_engine: Engine) -> None:
    """Uppercase hex input is normalised to lowercase on storage."""
    pk = _uid()
    digest = hashlib.sha256(b"content").hexdigest()
    upper_digest = digest.upper()
    with Session(db_engine) as s:
        s.add(_HashRow(id=pk, digest=upper_digest))
        s.commit()
    with Session(db_engine) as s:
        row = s.get(_HashRow, pk)
        assert row.digest == digest  # lowercase
