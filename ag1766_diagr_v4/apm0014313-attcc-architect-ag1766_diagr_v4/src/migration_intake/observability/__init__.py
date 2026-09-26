"""
Observability package for Migration Intake.

Provides structured logging with correlation ID propagation, stable event
codes, and credential redaction. All log records contain only enumerated
safe fields; sensitive data (tokens, credential URLs, answer bodies) must
never appear in log output.

Public API surface:
- generate_correlation_id / new_correlation_id: generate UUID v4 correlation IDs
- validate_correlation_id: check a candidate correlation ID
- redact_sensitive_url / redact_sensitive: mask credentials in URL strings
- StructuredLogger: safe structured logger bound to a correlation ID
- EventCode: class with stable UPPER_SNAKE_CASE event code constants
- Module-level event code aliases: WORKBOOK_PARSE_COMPLETED, etc.
"""

from __future__ import annotations

from migration_intake.observability.logging import (
    ANSWER_SAVED,
    APPLICATION_CREATED,
    CANDIDATE_ACCEPTED,
    CANDIDATE_MAPPING_COMPLETED,
    CANDIDATE_MAPPING_GROUNDING_FAILED,
    COMMAND_CONCURRENCY_CONFLICT,
    EVIDENCE_STORED,
    IMPORT_RUN_FAILED,
    INTAKE_CREATED,
    INTAKE_STATE_TRANSITION,
    ORACLE_CONNECTION_FAILED,
    SNAPSHOT_FROZEN,
    WORKBOOK_PARSE_COMPLETED,
    EventCode,
    StructuredLogger,
    generate_correlation_id,
    new_correlation_id,
    redact_sensitive,
    redact_sensitive_url,
    validate_correlation_id,
)

__all__ = [
    "ANSWER_SAVED",
    "APPLICATION_CREATED",
    "CANDIDATE_ACCEPTED",
    "CANDIDATE_MAPPING_COMPLETED",
    "CANDIDATE_MAPPING_GROUNDING_FAILED",
    "COMMAND_CONCURRENCY_CONFLICT",
    "EVIDENCE_STORED",
    "IMPORT_RUN_FAILED",
    "INTAKE_CREATED",
    "INTAKE_STATE_TRANSITION",
    "ORACLE_CONNECTION_FAILED",
    "SNAPSHOT_FROZEN",
    "WORKBOOK_PARSE_COMPLETED",
    "EventCode",
    "StructuredLogger",
    "generate_correlation_id",
    "new_correlation_id",
    "redact_sensitive",
    "redact_sensitive_url",
    "validate_correlation_id",
]
