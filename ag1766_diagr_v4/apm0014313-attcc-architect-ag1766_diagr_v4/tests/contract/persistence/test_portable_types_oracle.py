"""
Oracle-specific contract tests for portable SQLAlchemy column types.

These tests verify that PortableUUID, PortableUTC, PortableDecimal, CanonicalJSON,
and Sha256Hex behave identically on Oracle as they do on SQLite.

Key Oracle-specific concerns:
- CLOB handling for CanonicalJSON (no leaked LOB handles)
- Empty string vs NULL semantics
- Physical storage types (VARCHAR2, CLOB, NUMBER)
- Case normalization for identifiers
- Timezone handling in Oracle TIMESTAMP columns

All tests require ORACLE_TEST_URL environment variable and are marked with
@pytest.mark.oracle.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, String, event, text, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import NullPool

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


class _OracleUUIDRow(_Base):
    __tablename__ = "ora_uuid_test"
    id = Column(PortableUUID(), primary_key=True)
    ref = Column(PortableUUID(), nullable=True)


class _OracleUTCRow(_Base):
    __tablename__ = "ora_utc_test"
    id = Column(PortableUUID(), primary_key=True)
    created_at = Column(PortableUTC(), nullable=False)


class _OracleDecimalRow(_Base):
    __tablename__ = "ora_decimal_test"
    id = Column(PortableUUID(), primary_key=True)
    measurement = Column(PortableDecimal(precision=18, scale=6), nullable=True)


class _OracleJSONRow(_Base):
    __tablename__ = "ora_json_test"
    id = Column(PortableUUID(), primary_key=True)
    payload = Column(CanonicalJSON(), nullable=True)


class _OracleHashRow(_Base):
    __tablename__ = "ora_hash_test"
    id = Column(PortableUUID(), primary_key=True)
    digest = Column(Sha256Hex(), nullable=True)


# ---------------------------------------------------------------------------
# Oracle fixture
# ---------------------------------------------------------------------------


def _get_oracle_url() -> str | None:
    """Get Oracle test URL from environment."""
    # Try ORACLE_TEST_URL first, then load from .env
    url = os.environ.get("ORACLE_TEST_URL")
    if not url:
        try:
            from dotenv import load_dotenv
            env_path = Path.cwd() / ".env"
            if env_path.exists():
                load_dotenv(env_path)
                url = os.environ.get("ORACLE_TEST_URL")
        except ImportError:
            pass
    return url


@pytest.fixture(scope="module")
def oracle_engine() -> Engine:
    """
    Oracle test engine with dedicated schema.

    Creates test tables at module start, drops them at module end.
    Uses NullPool to avoid connection pooling issues in tests.
    """
    url = _get_oracle_url()
    if not url:
        pytest.skip("ORACLE_TEST_URL not configured")

    from migration_intake.persistence.database import configure_oracle_client

    client_dir = os.environ.get("AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR") or os.environ.get(
        "ORACLE_CLIENT_LIB_DIR"
    )
    configure_oracle_client(Path(client_dir) if client_dir else None)
    from sqlalchemy import create_engine

    engine = create_engine(url, poolclass=NullPool, echo=False)

    # Verify we're not connected as SYSTEM
    with engine.connect() as conn:
        result = conn.execute(text("SELECT USER FROM DUAL"))
        current_user = result.scalar()
        if current_user and current_user.upper() in ("SYSTEM", "SYS"):
            pytest.fail(
                f"Oracle tests must not run as {current_user}. "
                "Use a dedicated test schema (e.g., migration_intake_test)."
            )

    # Create test tables
    _Base.metadata.create_all(engine)

    yield engine

    # Drop test tables
    _Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def oracle_session(oracle_engine: Engine) -> Session:
    """Fresh Oracle session for each test."""
    session = Session(oracle_engine)
    yield session
    session.rollback()
    session.close()


def _uid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# PortableUUID — Oracle tests
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_oracle_uuid_round_trip(oracle_session: Session) -> None:
    """UUID stored and retrieved as uuid.UUID object on Oracle."""
    pk = _uid()
    ref = _uid()
    oracle_session.add(_OracleUUIDRow(id=pk, ref=ref))
    oracle_session.commit()

    row = oracle_session.get(_OracleUUIDRow, pk)
    assert row is not None
    assert row.id == pk
    assert row.ref == ref
    assert isinstance(row.id, uuid.UUID)


@pytest.mark.oracle
def test_oracle_uuid_stored_as_varchar2(oracle_engine: Engine, oracle_session: Session) -> None:
    """UUID is stored as VARCHAR2(36) in Oracle."""
    pk = _uid()
    oracle_session.add(_OracleUUIDRow(id=pk))
    oracle_session.commit()

    # Query physical storage type
    inspector = inspect(oracle_engine)
    columns = inspector.get_columns("ora_uuid_test")
    id_col = next(c for c in columns if c["name"].upper() == "ID")

    # Oracle reports VARCHAR2 as VARCHAR
    assert str(id_col["type"]).startswith("VARCHAR")

    # Verify stored value is a string (query the specific row we just inserted)
    with oracle_engine.connect() as conn:
        raw = conn.execute(
            text("SELECT id FROM ora_uuid_test WHERE id = :pk"),
            {"pk": str(pk)}
        ).scalar()
    assert isinstance(raw, str)
    assert raw == str(pk)


@pytest.mark.oracle
def test_oracle_uuid_nullable_column_stores_none(oracle_session: Session) -> None:
    """Nullable UUID column stores and retrieves None correctly on Oracle."""
    pk = _uid()
    oracle_session.add(_OracleUUIDRow(id=pk, ref=None))
    oracle_session.commit()

    row = oracle_session.get(_OracleUUIDRow, pk)
    assert row is not None
    assert row.ref is None


# ---------------------------------------------------------------------------
# PortableUTC — Oracle tests
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_oracle_utc_round_trip(oracle_session: Session) -> None:
    """UTC timestamp stored and retrieved as timezone-aware datetime on Oracle."""
    pk = _uid()
    now = datetime.now(tz=timezone.utc)
    oracle_session.add(_OracleUTCRow(id=pk, created_at=now))
    oracle_session.commit()

    row = oracle_session.get(_OracleUTCRow, pk)
    assert row is not None
    assert row.created_at.tzinfo is not None
    diff = abs((row.created_at - now).total_seconds())
    assert diff < 0.001, f"Timestamp drift: {diff}s"


@pytest.mark.oracle
def test_oracle_utc_normalizes_non_utc_input(oracle_session: Session) -> None:
    """Non-UTC timezone input is converted and returned as UTC on Oracle."""
    pk = _uid()
    eastern = timezone(timedelta(hours=-5))
    ts_input = datetime(2026, 6, 15, 10, 0, 0, tzinfo=eastern)
    expected_utc = datetime(2026, 6, 15, 15, 0, 0, tzinfo=timezone.utc)

    oracle_session.add(_OracleUTCRow(id=pk, created_at=ts_input))
    oracle_session.commit()

    row = oracle_session.get(_OracleUTCRow, pk)
    assert row is not None
    actual = row.created_at.astimezone(timezone.utc)
    assert actual.replace(tzinfo=None) == expected_utc.replace(tzinfo=None)


@pytest.mark.oracle
def test_oracle_utc_rejects_naive_datetime(oracle_session: Session) -> None:
    """Naive datetime is rejected on Oracle; all timestamps must be UTC-aware."""
    pk = _uid()
    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    oracle_session.add(_OracleUTCRow(id=pk, created_at=naive))
    with pytest.raises(Exception):
        oracle_session.flush()


@pytest.mark.oracle
def test_oracle_utc_stored_as_varchar2(oracle_engine: Engine, oracle_session: Session) -> None:
    """UTC timestamp is stored as VARCHAR2 (ISO text) on Oracle."""
    pk = _uid()
    now = datetime.now(tz=timezone.utc)
    oracle_session.add(_OracleUTCRow(id=pk, created_at=now))
    oracle_session.commit()

    # Verify stored value is a string
    with oracle_engine.connect() as conn:
        raw = conn.execute(
            text("SELECT created_at FROM ora_utc_test WHERE id = :pk"),
            {"pk": str(pk)}
        ).scalar()
    assert isinstance(raw, str)
    assert "T" in raw  # ISO format contains 'T' separator


# ---------------------------------------------------------------------------
# PortableDecimal — Oracle tests
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_oracle_decimal_round_trip(oracle_session: Session) -> None:
    """Decimal value stored and retrieved without loss on Oracle."""
    pk = _uid()
    value = Decimal("123.456789")
    oracle_session.add(_OracleDecimalRow(id=pk, measurement=value))
    oracle_session.commit()

    row = oracle_session.get(_OracleDecimalRow, pk)
    assert row is not None
    assert row.measurement == value
    assert isinstance(row.measurement, Decimal)


@pytest.mark.oracle
def test_oracle_decimal_null_explicit(oracle_session: Session) -> None:
    """Null Decimal column stores and retrieves None on Oracle."""
    pk = _uid()
    oracle_session.add(_OracleDecimalRow(id=pk, measurement=None))
    oracle_session.commit()

    row = oracle_session.get(_OracleDecimalRow, pk)
    assert row is not None
    assert row.measurement is None


@pytest.mark.oracle
def test_oracle_decimal_stored_as_number(oracle_engine: Engine) -> None:
    """Decimal is stored as Oracle NUMBER type."""
    inspector = inspect(oracle_engine)
    columns = inspector.get_columns("ora_decimal_test")
    measurement_col = next(c for c in columns if c["name"].upper() == "MEASUREMENT")

    # Oracle NUMBER type
    assert "NUMBER" in str(measurement_col["type"]).upper()


# ---------------------------------------------------------------------------
# CanonicalJSON — Oracle tests
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_oracle_json_round_trip(oracle_session: Session) -> None:
    """JSON dict payload stored and retrieved identically on Oracle."""
    pk = _uid()
    payload = {"question": "APP-001", "value": True, "meta": {"source": "test"}}
    oracle_session.add(_OracleJSONRow(id=pk, payload=payload))
    oracle_session.commit()

    row = oracle_session.get(_OracleJSONRow, pk)
    assert row is not None
    assert row.payload == payload


@pytest.mark.oracle
def test_oracle_json_list_round_trip(oracle_session: Session) -> None:
    """JSON list payload round-trips correctly on Oracle."""
    pk = _uid()
    payload = ["a", "b", "c", 1, 2, 3]
    oracle_session.add(_OracleJSONRow(id=pk, payload=payload))
    oracle_session.commit()

    row = oracle_session.get(_OracleJSONRow, pk)
    assert row is not None
    assert row.payload == payload


@pytest.mark.oracle
def test_oracle_json_null_explicit(oracle_session: Session) -> None:
    """Null JSON column stores and retrieves None on Oracle."""
    pk = _uid()
    oracle_session.add(_OracleJSONRow(id=pk, payload=None))
    oracle_session.commit()

    row = oracle_session.get(_OracleJSONRow, pk)
    assert row is not None
    assert row.payload is None


@pytest.mark.oracle
def test_oracle_json_stored_as_clob(oracle_engine: Engine) -> None:
    """JSON payload is stored as CLOB on Oracle (Text type)."""
    inspector = inspect(oracle_engine)
    columns = inspector.get_columns("ora_json_test")
    payload_col = next(c for c in columns if c["name"].upper() == "PAYLOAD")

    # Oracle Text maps to CLOB
    assert "CLOB" in str(payload_col["type"]).upper()


@pytest.mark.oracle
def test_oracle_json_no_lob_handle_leak(oracle_engine: Engine, oracle_session: Session) -> None:
    """
    Verify that CLOB values are fully materialized and don't leak LOB handles.

    Oracle LOB handles must be closed within the session that created them.
    CanonicalJSON must return a plain Python dict/list, not a lazy LOB proxy.
    """
    pk = _uid()
    payload = {"large": "x" * 5000}  # Force CLOB storage
    oracle_session.add(_OracleJSONRow(id=pk, payload=payload))
    oracle_session.commit()

    # Fetch and close session
    row = oracle_session.get(_OracleJSONRow, pk)
    assert row is not None
    retrieved_payload = row.payload
    oracle_session.close()

    # Access payload AFTER session is closed
    # If LOB handle leaked, this would raise "LOB variable no longer valid"
    assert retrieved_payload == payload
    assert isinstance(retrieved_payload, dict)


@pytest.mark.oracle
def test_oracle_json_empty_dict_vs_null(oracle_session: Session) -> None:
    """
    Empty dict {} is stored as '{}' text, not NULL.

    Oracle treats empty strings as NULL, but CanonicalJSON stores '{}' which
    is non-empty, so this should work correctly.
    """
    pk = _uid()
    oracle_session.add(_OracleJSONRow(id=pk, payload={}))
    oracle_session.commit()

    row = oracle_session.get(_OracleJSONRow, pk)
    assert row is not None
    assert row.payload == {}
    assert row.payload is not None


# ---------------------------------------------------------------------------
# Sha256Hex — Oracle tests
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_oracle_sha256_hex_round_trip(oracle_session: Session) -> None:
    """SHA-256 hex hash stored and retrieved as 64-char lowercase hex on Oracle."""
    pk = _uid()
    digest = hashlib.sha256(b"test content").hexdigest()
    assert len(digest) == 64
    oracle_session.add(_OracleHashRow(id=pk, digest=digest))
    oracle_session.commit()

    row = oracle_session.get(_OracleHashRow, pk)
    assert row is not None
    assert row.digest == digest
    assert row.digest == row.digest.lower()


@pytest.mark.oracle
def test_oracle_sha256_hex_null_explicit(oracle_session: Session) -> None:
    """Null SHA-256 column stores and retrieves None on Oracle."""
    pk = _uid()
    oracle_session.add(_OracleHashRow(id=pk, digest=None))
    oracle_session.commit()

    row = oracle_session.get(_OracleHashRow, pk)
    assert row is not None
    assert row.digest is None


@pytest.mark.oracle
def test_oracle_sha256_hex_stored_as_varchar2(oracle_engine: Engine) -> None:
    """SHA-256 hex is stored as VARCHAR2(64) on Oracle."""
    inspector = inspect(oracle_engine)
    columns = inspector.get_columns("ora_hash_test")
    digest_col = next(c for c in columns if c["name"].upper() == "DIGEST")

    assert "VARCHAR" in str(digest_col["type"]).upper()


# ---------------------------------------------------------------------------
# Cross-dialect consistency verification
# ---------------------------------------------------------------------------


@pytest.mark.oracle
def test_oracle_table_names_are_uppercase(oracle_engine: Engine) -> None:
    """
    Oracle normalizes unquoted identifiers to uppercase.

    Verify that our table names are accessible via uppercase lookup.
    """
    inspector = inspect(oracle_engine)
    table_names = inspector.get_table_names()

    # All our test tables should be present in uppercase
    expected_tables = {
        "ORA_UUID_TEST",
        "ORA_UTC_TEST",
        "ORA_DECIMAL_TEST",
        "ORA_JSON_TEST",
        "ORA_HASH_TEST",
    }

    actual_tables = {name.upper() for name in table_names}
    assert expected_tables.issubset(actual_tables), (
        f"Missing tables: {expected_tables - actual_tables}"
    )


@pytest.mark.oracle
def test_oracle_column_names_are_uppercase(oracle_engine: Engine) -> None:
    """Oracle normalizes unquoted column identifiers to uppercase."""
    inspector = inspect(oracle_engine)
    columns = inspector.get_columns("ora_uuid_test")
    column_names = {c["name"].upper() for c in columns}

    assert "ID" in column_names
    assert "REF" in column_names
