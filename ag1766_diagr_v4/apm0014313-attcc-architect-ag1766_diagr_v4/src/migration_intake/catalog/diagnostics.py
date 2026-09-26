"""
Catalog compiler diagnostics.

This module defines diagnostic structures for the catalog compiler,
including severity levels, diagnostic codes, and the compiler report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class DiagnosticSeverity(Enum):
    """
    Severity level for compiler diagnostics.

    ERROR: Blocks publication
    WARNING: Permits publication under explicit policy
    INFO: Informational, always permitted
    """

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"

    @property
    def blocks_publication(self) -> bool:
        """Whether this severity blocks catalog publication."""
        return self == DiagnosticSeverity.ERROR


class DiagnosticCodes:
    """
    Standard diagnostic codes for the catalog compiler.
    """

    # Error codes (block publication)
    DUPLICATE_ID = "DUPLICATE_ID"
    UNSUPPORTED_RESPONSE_TYPE = "UNSUPPORTED_RESPONSE_TYPE"
    INVALID_OPTION = "INVALID_OPTION"
    UNRESOLVED_DEPENDENCY = "UNRESOLVED_DEPENDENCY"
    MALFORMED_CONDITION = "MALFORMED_CONDITION"
    DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
    INVALID_SECTION = "INVALID_SECTION"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_UNIT = "INVALID_UNIT"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    UNKNOWN_DESTINATION = "UNKNOWN_DESTINATION"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"

    # Warning codes (permit under policy)
    MISSING_HELP_TEXT = "MISSING_HELP_TEXT"
    BROAD_SOURCE_LABEL = "BROAD_SOURCE_LABEL"
    MISSING_FRESHNESS_POLICY = "MISSING_FRESHNESS_POLICY"
    LEGACY_ALIAS_USED = "LEGACY_ALIAS_USED"
    DEPRECATED_FIELD = "DEPRECATED_FIELD"
    MISSING_DESCRIPTION = "MISSING_DESCRIPTION"

    # Info codes (always permitted)
    SECTION_COUNT = "SECTION_COUNT"
    QUESTION_COUNT = "QUESTION_COUNT"
    TYPE_COUNT = "TYPE_COUNT"
    ALIAS_NORMALIZED = "ALIAS_NORMALIZED"
    RELEASE_HASH = "RELEASE_HASH"
    COMPILATION_TIME = "COMPILATION_TIME"


@dataclass(frozen=True)
class Diagnostic:
    """
    A single diagnostic from the catalog compiler.

    Attributes:
        severity: Diagnostic severity level
        code: Diagnostic code from DiagnosticCodes
        message: Human-readable message
        row_number: Optional CSV row number
        question_id: Optional question ID
        field: Optional field name
        raw_value: Optional raw value that caused the diagnostic
        normalized_value: Optional normalized value
    """

    severity: DiagnosticSeverity
    code: str
    message: str
    row_number: int | None = None
    question_id: str | None = None
    field: str | None = None
    raw_value: str | None = None
    normalized_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
        }
        if self.row_number is not None:
            result["row_number"] = self.row_number
        if self.question_id is not None:
            result["question_id"] = self.question_id
        if self.field is not None:
            result["field"] = self.field
        if self.raw_value is not None:
            result["raw_value"] = self.raw_value
        if self.normalized_value is not None:
            result["normalized_value"] = self.normalized_value
        return result


class DiagnosticCollector:
    """
    Collects diagnostics during catalog compilation.

    Provides methods to add diagnostics and query the collection.
    """

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []

    def add(self, diagnostic: Diagnostic) -> None:
        """Add a diagnostic to the collection."""
        self._diagnostics.append(diagnostic)

    def error(
        self,
        code: str,
        message: str,
        *,
        row_number: int | None = None,
        question_id: str | None = None,
        field: str | None = None,
        raw_value: str | None = None,
    ) -> None:
        """Add an error diagnostic."""
        self.add(Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code=code,
            message=message,
            row_number=row_number,
            question_id=question_id,
            field=field,
            raw_value=raw_value,
        ))

    def warning(
        self,
        code: str,
        message: str,
        *,
        row_number: int | None = None,
        question_id: str | None = None,
        field: str | None = None,
        raw_value: str | None = None,
    ) -> None:
        """Add a warning diagnostic."""
        self.add(Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code=code,
            message=message,
            row_number=row_number,
            question_id=question_id,
            field=field,
            raw_value=raw_value,
        ))

    def info(
        self,
        code: str,
        message: str,
        *,
        row_number: int | None = None,
        question_id: str | None = None,
        field: str | None = None,
    ) -> None:
        """Add an info diagnostic."""
        self.add(Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code=code,
            message=message,
            row_number=row_number,
            question_id=question_id,
            field=field,
        ))

    def count(self) -> int:
        """Get total number of diagnostics."""
        return len(self._diagnostics)

    def error_count(self) -> int:
        """Get number of error diagnostics."""
        return sum(1 for d in self._diagnostics if d.severity == DiagnosticSeverity.ERROR)

    def warning_count(self) -> int:
        """Get number of warning diagnostics."""
        return sum(1 for d in self._diagnostics if d.severity == DiagnosticSeverity.WARNING)

    def info_count(self) -> int:
        """Get number of info diagnostics."""
        return sum(1 for d in self._diagnostics if d.severity == DiagnosticSeverity.INFO)

    def has_errors(self) -> bool:
        """Check if any error diagnostics exist."""
        return self.error_count() > 0

    def blocks_publication(self) -> bool:
        """Check if diagnostics block publication."""
        return self.has_errors()

    def get_by_severity(self, severity: DiagnosticSeverity) -> list[Diagnostic]:
        """Get diagnostics filtered by severity."""
        return [d for d in self._diagnostics if d.severity == severity]

    def all(self) -> list[Diagnostic]:
        """Get all diagnostics."""
        return list(self._diagnostics)

    def to_list(self) -> list[dict[str, Any]]:
        """Convert all diagnostics to list of dicts."""
        return [d.to_dict() for d in self._diagnostics]


@dataclass
class CompilerReport:
    """
    Report from catalog compilation.

    Contains compilation metadata, diagnostics, and summary statistics.

    Attributes:
        source_filename: Name of source file
        source_hash: SHA-256 hash of source
        compiler_version: Version of compiler
        diagnostics: Collected diagnostics
        section_count: Number of sections
        question_count: Number of questions
        type_counts: Count by response type
        compiled_at: Compilation timestamp
    """

    source_filename: str
    source_hash: str
    compiler_version: str
    diagnostics: DiagnosticCollector
    section_count: int
    question_count: int
    type_counts: dict[str, int] = field(default_factory=dict)
    compiled_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_success(self) -> bool:
        """Whether compilation succeeded (no errors)."""
        return not self.diagnostics.blocks_publication()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_filename": self.source_filename,
            "source_hash": self.source_hash,
            "compiler_version": self.compiler_version,
            "is_success": self.is_success,
            "section_count": self.section_count,
            "question_count": self.question_count,
            "type_counts": self.type_counts,
            "compiled_at": self.compiled_at.isoformat(),
            "error_count": self.diagnostics.error_count(),
            "warning_count": self.diagnostics.warning_count(),
            "info_count": self.diagnostics.info_count(),
            "diagnostics": self.diagnostics.to_list(),
        }
