"""
Tests for catalog diagnostics.

These tests verify:
- Diagnostic severity levels
- Diagnostic structure with row, field, and message
- Diagnostic collection and filtering
- Compiler report structure
"""

from __future__ import annotations

import pytest


class TestDiagnosticSeverity:
    """Tests for DiagnosticSeverity enumeration."""

    def test_severity_levels_defined(self) -> None:
        """DiagnosticSeverity should have ERROR, WARNING, INFO."""
        from migration_intake.catalog.diagnostics import DiagnosticSeverity

        assert hasattr(DiagnosticSeverity, "ERROR")
        assert hasattr(DiagnosticSeverity, "WARNING")
        assert hasattr(DiagnosticSeverity, "INFO")

    def test_error_is_highest_severity(self) -> None:
        """ERROR should be the highest severity."""
        from migration_intake.catalog.diagnostics import DiagnosticSeverity

        # ERROR should block publication
        assert DiagnosticSeverity.ERROR.blocks_publication is True
        assert DiagnosticSeverity.WARNING.blocks_publication is False
        assert DiagnosticSeverity.INFO.blocks_publication is False


class TestDiagnostic:
    """Tests for Diagnostic structure."""

    def test_diagnostic_has_required_fields(self) -> None:
        """Diagnostic should have severity, code, and message."""
        from migration_intake.catalog.diagnostics import Diagnostic, DiagnosticSeverity

        diag = Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="DUPLICATE_ID",
            message="Duplicate question ID: CTL-001",
        )

        assert diag.severity == DiagnosticSeverity.ERROR
        assert diag.code == "DUPLICATE_ID"
        assert "CTL-001" in diag.message

    def test_diagnostic_with_row_context(self) -> None:
        """Diagnostic should support row number context."""
        from migration_intake.catalog.diagnostics import Diagnostic, DiagnosticSeverity

        diag = Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="INVALID_TYPE",
            message="Unknown response type: CUSTOM",
            row_number=15,
        )

        assert diag.row_number == 15

    def test_diagnostic_with_question_id(self) -> None:
        """Diagnostic should support question ID context."""
        from migration_intake.catalog.diagnostics import Diagnostic, DiagnosticSeverity

        diag = Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="MISSING_HELP",
            message="Missing help text",
            question_id="APP-001",
        )

        assert diag.question_id == "APP-001"

    def test_diagnostic_with_field_context(self) -> None:
        """Diagnostic should support field name context."""
        from migration_intake.catalog.diagnostics import Diagnostic, DiagnosticSeverity

        diag = Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="INVALID_VALUE",
            message="Invalid value in Allowed_Values",
            field="Allowed_Values",
            raw_value="YES|NO|MAYBE",
        )

        assert diag.field == "Allowed_Values"
        assert diag.raw_value == "YES|NO|MAYBE"

    def test_diagnostic_is_immutable(self) -> None:
        """Diagnostic should be immutable."""
        from migration_intake.catalog.diagnostics import Diagnostic, DiagnosticSeverity

        diag = Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="TEST",
            message="Test message",
        )

        with pytest.raises((AttributeError, TypeError)):
            diag.code = "CHANGED"  # type: ignore[misc]


class TestDiagnosticCodes:
    """Tests for diagnostic code constants."""

    def test_error_codes_defined(self) -> None:
        """Error diagnostic codes should be defined."""
        from migration_intake.catalog.diagnostics import DiagnosticCodes

        # Errors that block publication
        assert hasattr(DiagnosticCodes, "DUPLICATE_ID")
        assert hasattr(DiagnosticCodes, "UNSUPPORTED_RESPONSE_TYPE")
        assert hasattr(DiagnosticCodes, "INVALID_OPTION")
        assert hasattr(DiagnosticCodes, "UNRESOLVED_DEPENDENCY")
        assert hasattr(DiagnosticCodes, "MALFORMED_CONDITION")
        assert hasattr(DiagnosticCodes, "DEPENDENCY_CYCLE")

    def test_warning_codes_defined(self) -> None:
        """Warning diagnostic codes should be defined."""
        from migration_intake.catalog.diagnostics import DiagnosticCodes

        # Warnings that don't block publication
        assert hasattr(DiagnosticCodes, "MISSING_HELP_TEXT")
        assert hasattr(DiagnosticCodes, "BROAD_SOURCE_LABEL")
        assert hasattr(DiagnosticCodes, "MISSING_FRESHNESS_POLICY")
        assert hasattr(DiagnosticCodes, "LEGACY_ALIAS_USED")

    def test_info_codes_defined(self) -> None:
        """Info diagnostic codes should be defined."""
        from migration_intake.catalog.diagnostics import DiagnosticCodes

        # Informational diagnostics
        assert hasattr(DiagnosticCodes, "SECTION_COUNT")
        assert hasattr(DiagnosticCodes, "QUESTION_COUNT")
        assert hasattr(DiagnosticCodes, "ALIAS_NORMALIZED")
        assert hasattr(DiagnosticCodes, "RELEASE_HASH")


class TestDiagnosticCollector:
    """Tests for DiagnosticCollector."""

    def test_collector_starts_empty(self) -> None:
        """DiagnosticCollector should start with no diagnostics."""
        from migration_intake.catalog.diagnostics import DiagnosticCollector

        collector = DiagnosticCollector()

        assert collector.count() == 0
        assert collector.has_errors() is False

    def test_collector_add_diagnostic(self) -> None:
        """DiagnosticCollector should accept diagnostics."""
        from migration_intake.catalog.diagnostics import (
            Diagnostic,
            DiagnosticCollector,
            DiagnosticSeverity,
        )

        collector = DiagnosticCollector()
        collector.add(Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="TEST",
            message="Test error",
        ))

        assert collector.count() == 1
        assert collector.has_errors() is True

    def test_collector_add_error_shorthand(self) -> None:
        """DiagnosticCollector should have error shorthand."""
        from migration_intake.catalog.diagnostics import DiagnosticCollector

        collector = DiagnosticCollector()
        collector.error("DUPLICATE_ID", "Duplicate ID found", row_number=5)

        assert collector.has_errors() is True
        assert collector.error_count() == 1

    def test_collector_add_warning_shorthand(self) -> None:
        """DiagnosticCollector should have warning shorthand."""
        from migration_intake.catalog.diagnostics import DiagnosticCollector

        collector = DiagnosticCollector()
        collector.warning("MISSING_HELP", "Missing help text", question_id="APP-001")

        assert collector.has_errors() is False
        assert collector.warning_count() == 1

    def test_collector_add_info_shorthand(self) -> None:
        """DiagnosticCollector should have info shorthand."""
        from migration_intake.catalog.diagnostics import DiagnosticCollector

        collector = DiagnosticCollector()
        collector.info("QUESTION_COUNT", "Total questions: 112")

        assert collector.info_count() == 1

    def test_collector_filter_by_severity(self) -> None:
        """DiagnosticCollector should filter by severity."""
        from migration_intake.catalog.diagnostics import (
            DiagnosticCollector,
            DiagnosticSeverity,
        )

        collector = DiagnosticCollector()
        collector.error("ERR1", "Error 1")
        collector.error("ERR2", "Error 2")
        collector.warning("WARN1", "Warning 1")
        collector.info("INFO1", "Info 1")

        errors = collector.get_by_severity(DiagnosticSeverity.ERROR)
        warnings = collector.get_by_severity(DiagnosticSeverity.WARNING)

        assert len(errors) == 2
        assert len(warnings) == 1

    def test_collector_blocks_publication_with_errors(self) -> None:
        """DiagnosticCollector should block publication when errors exist."""
        from migration_intake.catalog.diagnostics import DiagnosticCollector

        collector = DiagnosticCollector()
        collector.warning("WARN1", "Warning only")

        assert collector.blocks_publication() is False

        collector.error("ERR1", "Error added")

        assert collector.blocks_publication() is True

    def test_collector_all_diagnostics(self) -> None:
        """DiagnosticCollector should return all diagnostics."""
        from migration_intake.catalog.diagnostics import DiagnosticCollector

        collector = DiagnosticCollector()
        collector.error("ERR1", "Error")
        collector.warning("WARN1", "Warning")
        collector.info("INFO1", "Info")

        all_diags = collector.all()

        assert len(all_diags) == 3


class TestCompilerReport:
    """Tests for CompilerReport structure."""

    def test_report_has_required_fields(self) -> None:
        """CompilerReport should have all required fields."""
        from migration_intake.catalog.diagnostics import (
            CompilerReport,
            DiagnosticCollector,
        )

        collector = DiagnosticCollector()
        collector.info("QUESTION_COUNT", "112 questions")

        report = CompilerReport(
            source_filename="QUESTION_CATALOG_V0_2.csv",
            source_hash="abc123def456",
            compiler_version="1.0.0",
            diagnostics=collector,
            section_count=10,
            question_count=112,
        )

        assert report.source_filename == "QUESTION_CATALOG_V0_2.csv"
        assert report.source_hash == "abc123def456"
        assert report.section_count == 10
        assert report.question_count == 112

    def test_report_success_status(self) -> None:
        """CompilerReport should indicate success when no errors."""
        from migration_intake.catalog.diagnostics import (
            CompilerReport,
            DiagnosticCollector,
        )

        collector = DiagnosticCollector()
        collector.info("INFO1", "Info only")

        report = CompilerReport(
            source_filename="test.csv",
            source_hash="abc123",
            compiler_version="1.0.0",
            diagnostics=collector,
            section_count=1,
            question_count=10,
        )

        assert report.is_success is True

    def test_report_failure_status(self) -> None:
        """CompilerReport should indicate failure when errors exist."""
        from migration_intake.catalog.diagnostics import (
            CompilerReport,
            DiagnosticCollector,
        )

        collector = DiagnosticCollector()
        collector.error("ERR1", "Error found")

        report = CompilerReport(
            source_filename="test.csv",
            source_hash="abc123",
            compiler_version="1.0.0",
            diagnostics=collector,
            section_count=1,
            question_count=10,
        )

        assert report.is_success is False

    def test_report_type_counts(self) -> None:
        """CompilerReport should include response type counts."""
        from migration_intake.catalog.diagnostics import (
            CompilerReport,
            DiagnosticCollector,
        )

        collector = DiagnosticCollector()

        report = CompilerReport(
            source_filename="test.csv",
            source_hash="abc123",
            compiler_version="1.0.0",
            diagnostics=collector,
            section_count=10,
            question_count=112,
            type_counts={"BOOLEAN": 14, "TEXT": 20, "SINGLE_SELECT": 5},
        )

        assert report.type_counts["BOOLEAN"] == 14
        assert report.type_counts["TEXT"] == 20

    def test_report_to_dict(self) -> None:
        """CompilerReport should serialize to dict."""
        from migration_intake.catalog.diagnostics import (
            CompilerReport,
            DiagnosticCollector,
        )

        collector = DiagnosticCollector()
        collector.info("INFO1", "Test info")

        report = CompilerReport(
            source_filename="test.csv",
            source_hash="abc123",
            compiler_version="1.0.0",
            diagnostics=collector,
            section_count=1,
            question_count=10,
        )

        data = report.to_dict()

        assert data["source_filename"] == "test.csv"
        assert data["is_success"] is True
        assert "diagnostics" in data
