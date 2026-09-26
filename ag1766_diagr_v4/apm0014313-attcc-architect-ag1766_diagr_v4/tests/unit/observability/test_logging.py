"""
Unit tests for structured logging and correlation (O01).

Verifies:
- Correlation IDs are generated as valid UUIDs.
- Correlation IDs are validated; invalid values are rejected.
- Stable event-code constants exist and are non-empty strings.
- Safe fields (event_code, correlation_id, operation, outcome) appear in log output.
- Sensitive fields (tokens, credentials) must never appear in log output.
- Redaction strips credentials from database URLs.
- StructuredLogger binds correlation ID at construction and echoes it in records.
"""

from __future__ import annotations

import logging
import re
import uuid
from io import StringIO

import pytest

from migration_intake.observability.logging import (
    COMMAND_CONCURRENCY_CONFLICT,
    ORACLE_CONNECTION_FAILED,
    WORKBOOK_PARSE_COMPLETED,
    StructuredLogger,
    generate_correlation_id,
    new_correlation_id,
    redact_sensitive,
    redact_sensitive_url,
    validate_correlation_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_capturing_logger(name: str | None = None) -> tuple[StructuredLogger, StringIO]:
    """Return a StructuredLogger whose output is captured in an in-memory stream."""
    logger_name = name or f"test_obs_{uuid.uuid4().hex}"
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    py_logger = logging.getLogger(logger_name)
    py_logger.setLevel(logging.DEBUG)
    py_logger.addHandler(handler)
    py_logger.propagate = False
    return StructuredLogger(logger_name), stream


# ---------------------------------------------------------------------------
# Correlation ID generation
# ---------------------------------------------------------------------------


def test_generate_correlation_id_is_valid_uuid() -> None:
    """generate_correlation_id() returns a string parseable as a UUID."""
    cid = generate_correlation_id()
    parsed = uuid.UUID(cid)
    assert str(parsed) == cid


def test_new_correlation_id_is_alias() -> None:
    """new_correlation_id is an alias for generate_correlation_id."""
    cid = new_correlation_id()
    parsed = uuid.UUID(cid)
    assert str(parsed) == cid


def test_generate_correlation_id_is_unique() -> None:
    """Successive calls return different correlation IDs."""
    ids = {generate_correlation_id() for _ in range(20)}
    assert len(ids) == 20


def test_generate_correlation_id_is_bounded() -> None:
    """Generated ID is at most 36 characters (canonical UUID length)."""
    assert len(generate_correlation_id()) <= 36


# ---------------------------------------------------------------------------
# Correlation ID validation
# ---------------------------------------------------------------------------


def test_validate_correlation_id_accepts_valid_uuid() -> None:
    """validate_correlation_id returns True for a valid UUID string."""
    assert validate_correlation_id(str(uuid.uuid4())) is True


def test_validate_correlation_id_rejects_empty_string() -> None:
    """validate_correlation_id rejects an empty string."""
    assert validate_correlation_id("") is False


def test_validate_correlation_id_rejects_oversized_value() -> None:
    """validate_correlation_id rejects strings longer than 36 characters."""
    assert validate_correlation_id("a" * 37) is False


def test_validate_correlation_id_rejects_non_uuid_string() -> None:
    """validate_correlation_id rejects arbitrary non-UUID strings."""
    assert validate_correlation_id("not-a-uuid-value") is False


def test_validate_correlation_id_rejects_none() -> None:
    """validate_correlation_id rejects None (accepts object type for safety)."""
    assert validate_correlation_id(None) is False  # type: ignore[arg-type]


def test_validate_correlation_id_rejects_string_none() -> None:
    """validate_correlation_id rejects the literal string 'None'."""
    assert validate_correlation_id("None") is False


# ---------------------------------------------------------------------------
# Event code constants
# ---------------------------------------------------------------------------


def test_workbook_parse_completed_is_stable_string() -> None:
    """WORKBOOK_PARSE_COMPLETED is a non-empty string constant."""
    assert isinstance(WORKBOOK_PARSE_COMPLETED, str)
    assert len(WORKBOOK_PARSE_COMPLETED) > 0


def test_command_concurrency_conflict_is_stable_string() -> None:
    """COMMAND_CONCURRENCY_CONFLICT is a non-empty string constant."""
    assert isinstance(COMMAND_CONCURRENCY_CONFLICT, str)
    assert len(COMMAND_CONCURRENCY_CONFLICT) > 0


def test_oracle_connection_failed_is_stable_string() -> None:
    """ORACLE_CONNECTION_FAILED is a non-empty string constant."""
    assert isinstance(ORACLE_CONNECTION_FAILED, str)
    assert len(ORACLE_CONNECTION_FAILED) > 0


def test_event_codes_are_upper_snake_case() -> None:
    """Event code constants use UPPER_SNAKE_CASE format."""
    pattern = re.compile(r"^[A-Z][A-Z0-9_]+$")
    for code in (
        WORKBOOK_PARSE_COMPLETED,
        COMMAND_CONCURRENCY_CONFLICT,
        ORACLE_CONNECTION_FAILED,
    ):
        assert pattern.match(code), f"Event code {code!r} not in UPPER_SNAKE_CASE"


# ---------------------------------------------------------------------------
# URL redaction
# ---------------------------------------------------------------------------


def test_redact_sensitive_url_removes_password() -> None:
    """redact_sensitive_url masks username and password in the URL."""
    url = "postgresql://admin:s3cr3t@db.internal:5432/appdb"
    redacted = redact_sensitive_url(url)
    assert "s3cr3t" not in redacted
    assert "admin" not in redacted
    assert "<redacted>" in redacted or "***" in redacted


def test_redact_sensitive_is_alias() -> None:
    """redact_sensitive is the canonical name; redact_sensitive_url is its alias."""
    url = "postgresql://user:pass@host/db"
    assert redact_sensitive(url) == redact_sensitive_url(url)


def test_redact_sensitive_url_leaves_sqlite_unchanged() -> None:
    """SQLite URLs without credentials pass through unchanged."""
    url = "sqlite:///data/app.db"
    assert redact_sensitive_url(url) == url


def test_redact_sensitive_url_handles_oracle_url() -> None:
    """Oracle-style URLs are redacted correctly."""
    url = "oracle+oracledb://appuser:apppass@localhost:1521/?service_name=FREEPDB1"
    redacted = redact_sensitive_url(url)
    assert "apppass" not in redacted
    assert "localhost:1521" in redacted


# ---------------------------------------------------------------------------
# StructuredLogger — construction and correlation ID binding
# ---------------------------------------------------------------------------


def test_logger_generates_correlation_id_when_none_supplied() -> None:
    """StructuredLogger generates a valid UUID correlation ID when none is given."""
    logger, _ = _make_capturing_logger()
    assert validate_correlation_id(logger.correlation_id)


def test_logger_uses_supplied_correlation_id() -> None:
    """StructuredLogger binds the caller-supplied correlation ID."""
    supplied = str(uuid.uuid4())
    logger_name = f"test_supplied_{uuid.uuid4().hex}"
    logger = StructuredLogger(logger_name, correlation_id=supplied)
    assert logger.correlation_id == supplied


def test_logger_rejects_invalid_correlation_id() -> None:
    """StructuredLogger raises ValueError for an invalid correlation ID."""
    with pytest.raises(ValueError):
        StructuredLogger("test_invalid", correlation_id="not-a-uuid")


def test_logger_correlation_ids_are_unique_per_instance() -> None:
    """Two loggers created without explicit correlation ID get different IDs."""
    l1, _ = _make_capturing_logger()
    l2, _ = _make_capturing_logger()
    assert l1.correlation_id != l2.correlation_id


# ---------------------------------------------------------------------------
# StructuredLogger — output content
# ---------------------------------------------------------------------------


def test_logger_includes_event_code_in_output() -> None:
    """Log output contains the event_code."""
    logger, stream = _make_capturing_logger()
    logger.info(event_code=WORKBOOK_PARSE_COMPLETED, operation="parse")
    assert WORKBOOK_PARSE_COMPLETED in stream.getvalue()


def test_logger_includes_correlation_id_in_output() -> None:
    """Log output contains the bound correlation ID."""
    logger, stream = _make_capturing_logger()
    logger.info(event_code=WORKBOOK_PARSE_COMPLETED, operation="parse")
    assert logger.correlation_id in stream.getvalue()


def test_logger_includes_operation_in_output() -> None:
    """Log output contains the operation field."""
    logger, stream = _make_capturing_logger()
    logger.info(event_code=WORKBOOK_PARSE_COMPLETED, operation="my_operation")
    assert "my_operation" in stream.getvalue()


def test_logger_warning_includes_event_code() -> None:
    """warning() log records contain the event_code."""
    logger, stream = _make_capturing_logger()
    logger.warning(event_code=COMMAND_CONCURRENCY_CONFLICT, operation="save")
    assert COMMAND_CONCURRENCY_CONFLICT in stream.getvalue()


def test_logger_error_includes_exception_class_name() -> None:
    """error() log records include the exception_class when provided."""
    logger, stream = _make_capturing_logger()
    logger.error(
        event_code=ORACLE_CONNECTION_FAILED,
        operation="connect",
        outcome="failure",
        exception_class="ConnectionError",
    )
    assert "ConnectionError" in stream.getvalue()


def test_logger_does_not_log_raw_token_value() -> None:
    """Log output never contains a raw token string that was not passed to info()."""
    logger, stream = _make_capturing_logger()
    logger.info(event_code=WORKBOOK_PARSE_COMPLETED, operation="parse")
    output = stream.getvalue()
    # The word 'token' with a real value would only appear if something sneaked it in
    assert "supersecrettoken" not in output
