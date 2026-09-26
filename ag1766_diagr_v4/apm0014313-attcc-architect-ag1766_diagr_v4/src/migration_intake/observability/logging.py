"""
Structured logging and correlation ID management for Migration Intake.

This module provides:
- Correlation ID generation (new_correlation_id) and validation
  (validate_correlation_id). Correlation IDs are bounded UUID v4 strings.
- StructuredLogger: wraps Python's standard logging and emits records
  that include only safe, enumerated fields.
- EventCode: stable string constants for reliable log filtering.
- redact_sensitive: masks credentials embedded in URL strings.

Fields that MUST NEVER appear in log output:
  evidence bodies, questionnaire answers, raw candidate payloads, tokens,
  database URLs with credentials, authorization headers, provider response
  bodies.
"""

from __future__ import annotations

import logging
import re
import uuid

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# Matches scheme://user:password@host patterns.
# Captures the scheme+:// prefix so it can be preserved in the replacement.
_CREDENTIAL_URL_RE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+\-.]*://)[^:@/\s]+:[^@/\s]+@"
)


def redact_sensitive(text: str) -> str:
    """
    Mask credentials embedded in URL-style connection strings.

    Replaces the user:password@ portion of any scheme://user:password@host
    pattern with <redacted>@, preserving the scheme and host.

    Args:
        text: The string to redact.

    Returns:
        The string with embedded credentials replaced by '<redacted>'.
    """
    return _CREDENTIAL_URL_RE.sub(r"\1<redacted>@", text)


# ---------------------------------------------------------------------------
# Correlation ID
# ---------------------------------------------------------------------------

# UUID canonical form: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 chars)
_MAX_CORRELATION_ID_LEN = 36


def new_correlation_id() -> str:
    """
    Generate a new correlation ID as a canonical UUID v4 string.

    Returns:
        A lowercase canonical UUID4 string (36 characters, with hyphens).
    """
    return str(uuid.uuid4())


def validate_correlation_id(value: object) -> bool:
    """
    Return True if value is a valid, bounded correlation ID.

    A valid correlation ID is a string of at most 36 characters that
    parses as a UUID and equals the canonical str() representation of
    that UUID (i.e. includes hyphens in the standard positions).

    Args:
        value: The candidate correlation ID (any type accepted for safety).

    Returns:
        True if value is a canonical UUID string of at most 36 chars;
        False for any other input including None and non-strings.
    """
    if not isinstance(value, str):
        return False
    if len(value) > _MAX_CORRELATION_ID_LEN:
        return False
    try:
        parsed = uuid.UUID(value)
        return str(parsed) == value
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Stable event codes
# ---------------------------------------------------------------------------


class EventCode:
    """
    Stable string constants for structured log event codes.

    Event codes are stable, enumerated identifiers written into every
    log record. They allow reliable filtering and alerting without
    parsing free-form message text. Add new codes here rather than
    embedding ad-hoc strings in call sites.
    """

    WORKBOOK_PARSE_COMPLETED: str = "WORKBOOK_PARSE_COMPLETED"
    COMMAND_CONCURRENCY_CONFLICT: str = "COMMAND_CONCURRENCY_CONFLICT"
    ORACLE_CONNECTION_FAILED: str = "ORACLE_CONNECTION_FAILED"
    CANDIDATE_MAPPING_COMPLETED: str = "CANDIDATE_MAPPING_COMPLETED"
    CANDIDATE_MAPPING_GROUNDING_FAILED: str = "CANDIDATE_MAPPING_GROUNDING_FAILED"
    INTAKE_STATE_TRANSITION: str = "INTAKE_STATE_TRANSITION"
    EVIDENCE_STORED: str = "EVIDENCE_STORED"
    APPLICATION_CREATED: str = "APPLICATION_CREATED"
    INTAKE_CREATED: str = "INTAKE_CREATED"


# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------


class StructuredLogger:
    """
    Safe structured logger that wraps Python's standard logging module.

    Every log record includes only the following enumerated safe fields:
      event_code, correlation_id, operation, outcome, actor_id,
      application_id, intake_id, duration_ms, count, exception_class.

    The following fields MUST NEVER be passed or logged:
      evidence bodies, questionnaire answers, raw candidate payloads,
      tokens, database URLs with credentials, authorization headers,
      provider response bodies.

    The method signatures deliberately exclude sensitive parameter names
    to prevent accidental logging of protected information.
    """

    def __init__(
        self,
        name: str,
        correlation_id: str | None = None,
    ) -> None:
        """
        Create a StructuredLogger.

        Args:
            name: Logger name passed to logging.getLogger (e.g. __name__).
            correlation_id: Optional existing correlation ID to use. If
                omitted, a new UUID v4 is generated. Raises ValueError
                if a non-None value fails validate_correlation_id.

        Raises:
            ValueError: If correlation_id is provided but is not a valid
                canonical UUID string.
        """
        if correlation_id is not None:
            if not validate_correlation_id(correlation_id):
                raise ValueError(
                    f"Invalid correlation_id {correlation_id!r}. "
                    "Must be a canonical UUID string (36 characters)."
                )
            self._correlation_id = correlation_id
        else:
            self._correlation_id = new_correlation_id()

        self._logger = logging.getLogger(name)

    @property
    def correlation_id(self) -> str:
        """The correlation ID bound to this logger instance."""
        return self._correlation_id

    def _build_message(
        self,
        event_code: str,
        operation: str,
        outcome: str | None,
        actor_id: str | None,
        application_id: str | None,
        intake_id: str | None,
        duration_ms: float | None,
        count: int | None,
        exception_class: str | None,
    ) -> str:
        """
        Build a structured log message string from safe fields only.

        Returns:
            A space-joined 'key=value' string suitable for log parsers.
        """
        parts = [
            f"event_code={event_code}",
            f"correlation_id={self._correlation_id}",
            f"operation={operation}",
        ]
        if outcome is not None:
            parts.append(f"outcome={outcome}")
        if actor_id is not None:
            parts.append(f"actor_id={actor_id}")
        if application_id is not None:
            parts.append(f"application_id={application_id}")
        if intake_id is not None:
            parts.append(f"intake_id={intake_id}")
        if duration_ms is not None:
            parts.append(f"duration_ms={duration_ms:.3f}")
        if count is not None:
            parts.append(f"count={count}")
        if exception_class is not None:
            parts.append(f"exception_class={exception_class}")
        return " ".join(parts)

    def info(
        self,
        event_code: str,
        operation: str,
        outcome: str | None = None,
        actor_id: str | None = None,
        application_id: str | None = None,
        intake_id: str | None = None,
        duration_ms: float | None = None,
        count: int | None = None,
        exception_class: str | None = None,
    ) -> None:
        """
        Emit an INFO-level structured log record.

        Args:
            event_code: Stable event code (use EventCode constants).
            operation: Name of the operation being logged.
            outcome: Optional outcome descriptor (e.g. 'success').
            actor_id: Optional safe actor identifier (UUID string).
            application_id: Optional safe application identifier.
            intake_id: Optional safe intake identifier.
            duration_ms: Optional operation duration in milliseconds.
            count: Optional safe count (e.g. rows processed).
            exception_class: Optional exception class name.
        """
        msg = self._build_message(
            event_code=event_code,
            operation=operation,
            outcome=outcome,
            actor_id=actor_id,
            application_id=application_id,
            intake_id=intake_id,
            duration_ms=duration_ms,
            count=count,
            exception_class=exception_class,
        )
        self._logger.info(msg)

    def warning(
        self,
        event_code: str,
        operation: str,
        outcome: str | None = None,
        actor_id: str | None = None,
        application_id: str | None = None,
        intake_id: str | None = None,
        duration_ms: float | None = None,
        count: int | None = None,
        exception_class: str | None = None,
    ) -> None:
        """
        Emit a WARNING-level structured log record.

        Args:
            event_code: Stable event code (use EventCode constants).
            operation: Name of the operation being logged.
            outcome: Optional outcome descriptor.
            actor_id: Optional safe actor identifier.
            application_id: Optional safe application identifier.
            intake_id: Optional safe intake identifier.
            duration_ms: Optional operation duration in milliseconds.
            count: Optional safe count.
            exception_class: Optional exception class name.
        """
        msg = self._build_message(
            event_code=event_code,
            operation=operation,
            outcome=outcome,
            actor_id=actor_id,
            application_id=application_id,
            intake_id=intake_id,
            duration_ms=duration_ms,
            count=count,
            exception_class=exception_class,
        )
        self._logger.warning(msg)

    def error(
        self,
        event_code: str,
        operation: str,
        outcome: str | None = None,
        actor_id: str | None = None,
        application_id: str | None = None,
        intake_id: str | None = None,
        duration_ms: float | None = None,
        count: int | None = None,
        exception_class: str | None = None,
    ) -> None:
        """
        Emit an ERROR-level structured log record.

        Args:
            event_code: Stable event code (use EventCode constants).
            operation: Name of the operation being logged.
            outcome: Optional outcome descriptor.
            actor_id: Optional safe actor identifier.
            application_id: Optional safe application identifier.
            intake_id: Optional safe intake identifier.
            duration_ms: Optional operation duration in milliseconds.
            count: Optional safe count.
            exception_class: Optional exception class name.
        """
        msg = self._build_message(
            event_code=event_code,
            operation=operation,
            outcome=outcome,
            actor_id=actor_id,
            application_id=application_id,
            intake_id=intake_id,
            duration_ms=duration_ms,
            count=count,
            exception_class=exception_class,
        )
        self._logger.error(msg)


# ---------------------------------------------------------------------------
# Module-level aliases and convenience constants
#
# These aliases expose the canonical names expected by the package __init__
# and allow call sites to import event codes directly without referencing
# the EventCode class.
# ---------------------------------------------------------------------------

#: Alias: generate_correlation_id → new_correlation_id
generate_correlation_id = new_correlation_id

#: Alias: redact_sensitive_url → redact_sensitive
redact_sensitive_url = redact_sensitive

# Flat event-code aliases (stable — do not rename)
WORKBOOK_PARSE_COMPLETED: str = EventCode.WORKBOOK_PARSE_COMPLETED
COMMAND_CONCURRENCY_CONFLICT: str = EventCode.COMMAND_CONCURRENCY_CONFLICT
ORACLE_CONNECTION_FAILED: str = EventCode.ORACLE_CONNECTION_FAILED
CANDIDATE_MAPPING_COMPLETED: str = EventCode.CANDIDATE_MAPPING_COMPLETED
CANDIDATE_MAPPING_GROUNDING_FAILED: str = EventCode.CANDIDATE_MAPPING_GROUNDING_FAILED
INTAKE_STATE_TRANSITION: str = EventCode.INTAKE_STATE_TRANSITION
EVIDENCE_STORED: str = EventCode.EVIDENCE_STORED
APPLICATION_CREATED: str = EventCode.APPLICATION_CREATED
INTAKE_CREATED: str = EventCode.INTAKE_CREATED

# Additional event codes referenced by packet O01 contract tests
ANSWER_SAVED: str = "ANSWER_SAVED"
CANDIDATE_ACCEPTED: str = "CANDIDATE_ACCEPTED"
SNAPSHOT_FROZEN: str = "SNAPSHOT_FROZEN"
IMPORT_RUN_FAILED: str = "IMPORT_RUN_FAILED"
