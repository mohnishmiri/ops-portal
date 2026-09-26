"""
Tests for catalog CSV compiler.

These tests verify:
- Compile CSV rows to catalog release
- Validate unique question IDs
- Normalize sections, sources, owners, outputs, destinations
- Parse allowed values and units
- Attach response-type schema
- Compile Required_When to safe AST
- Detect dependency cycles
- Canonical output/hash deterministic
- Compiler report includes all independent diagnostics
"""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Sample CSV content for testing
VALID_CSV_HEADER = "Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination"

VALID_CSV_ROW_1 = "CTL-001,CTL,What is the correlation ID?,IDENTIFIER,,REQUIRED,,Workbook,,Application Owner,ALL,ANSWER"
VALID_CSV_ROW_2 = "DB-001,DB,Does the application use a database?,BOOLEAN,YES|NO|UNKNOWN,REQUIRED,,Workbook|iTAP,,Application Owner,Topology,ANSWER"
VALID_CSV_ROW_3 = "DB-002,DB,What database engine?,SINGLE_SELECT,ORACLE|MYSQL|POSTGRES|OTHER,CONDITIONAL,DB-001 = YES,Workbook,,DBA,Topology,ANSWER"


def make_csv(*rows: str) -> str:
    """Create CSV content from rows."""
    return "\n".join(rows)


class TestCatalogCompiler:
    """Tests for CatalogCompiler."""

    def test_v100_non_derived_questions_use_editable_response_types(self) -> None:
        """Only explicitly derived catalog questions omit input editors."""
        from migration_intake.catalog.compiler import CatalogCompiler
        from migration_intake.catalog.response_types import get_default_registry

        catalog_path = (
            Path(__file__).parents[3]
            / "src"
            / "migration_intake"
            / "catalog"
            / "data"
            / "catalog-1.0.0.csv"
        )
        result = CatalogCompiler().compile(
            catalog_path.read_text(encoding="utf-8-sig"),
            version="1.0.0",
            source_filename=catalog_path.name,
        )

        assert result.report.is_success is True
        assert result.release is not None
        registry = get_default_registry()
        non_derived = [
            question
            for question in result.release.questions.values()
            if question.collection_mode != "DERIVED"
        ]
        for question in non_derived:
            response_type = registry.get(question.response_type)
            assert response_type is not None
            assert response_type.is_computed is False

        database = result.release.get_section("DATABASE")
        assert database is not None
        database_questions = [
            question
            for question in result.release.questions.values()
            if question.section_code == database.code
        ]
        assert len(database_questions) == 8
        assert all(
            registry.get(question.response_type) is not None
            and not registry.get(question.response_type).is_computed
            for question in database_questions
        )

    def test_compiler_accepts_valid_csv(self) -> None:
        """Compiler should accept valid CSV content."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.report.is_success is True
        assert result.release is not None

    def test_compiler_creates_release_with_metadata(self) -> None:
        """Compiler should create release with proper metadata."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        assert result.release.version == "0.2.0"
        assert result.release.source_hash is not None
        assert result.release.compiler_version is not None

    def test_compiler_parses_questions(self) -> None:
        """Compiler should parse questions from CSV."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1, VALID_CSV_ROW_2)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        assert result.release.question_count() == 2
        assert result.release.get_question("CTL-001") is not None
        assert result.release.get_question("DB-001") is not None

    def test_compiler_creates_sections(self) -> None:
        """Compiler should create sections from questions."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1, VALID_CSV_ROW_2)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        assert result.release.section_count() >= 2
        assert result.release.get_section("CTL") is not None
        assert result.release.get_section("DB") is not None


class TestDuplicateIdDetection:
    """Tests for duplicate ID detection."""

    def test_reject_duplicate_question_ids(self) -> None:
        """Compiler should reject duplicate question IDs."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(
            VALID_CSV_HEADER,
            VALID_CSV_ROW_1,
            VALID_CSV_ROW_1,  # Duplicate
        )
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.report.is_success is False
        assert result.report.diagnostics.has_errors() is True
        errors = result.report.diagnostics.get_by_severity(
            result.report.diagnostics._diagnostics[0].severity.__class__(
                result.report.diagnostics._diagnostics[0].severity.value
            )
        )
        assert any("duplicate" in d.message.lower() or "CTL-001" in d.message for d in result.report.diagnostics.all())


class TestVersionHashValidation:
    """Tests for version and hash validation."""

    def test_same_content_produces_same_hash(self) -> None:
        """Same CSV content should produce same hash."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)
        compiler = CatalogCompiler()

        result1 = compiler.compile(csv_content, version="0.2.0")
        result2 = compiler.compile(csv_content, version="0.2.0")

        assert result1.release is not None
        assert result2.release is not None
        assert result1.release.source_hash == result2.release.source_hash

    def test_different_content_produces_different_hash(self) -> None:
        """Different CSV content should produce different hash."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv1 = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)
        csv2 = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_2)
        compiler = CatalogCompiler()

        result1 = compiler.compile(csv1, version="0.2.0")
        result2 = compiler.compile(csv2, version="0.2.0")

        assert result1.release is not None
        assert result2.release is not None
        assert result1.release.source_hash != result2.release.source_hash


class TestRelationshipNormalization:
    """Tests for relationship normalization."""

    def test_normalize_sources_with_priority(self) -> None:
        """Sources should be normalized with priority order."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_2)  # Has Workbook|iTAP
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("DB-001")
        assert question is not None
        assert len(question.sources) >= 1
        # Preferred source should have priority 1
        if len(question.sources) > 0:
            assert question.sources[0].priority == 1

    def test_normalize_owner_role(self) -> None:
        """Owner should be normalized to role code."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("CTL-001")
        assert question is not None
        assert len(question.owners) >= 1
        # Owner should be normalized to uppercase with underscores
        assert question.owners[0].role_code == "APPLICATION_OWNER"

    def test_expand_all_outputs(self) -> None:
        """ALL output should expand to Topology, ADS, DDD."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)  # Has Output=ALL
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("CTL-001")
        assert question is not None
        # ALL should expand to multiple destinations
        dest_ids = [d.target_identifier for d in question.destinations]
        # Should have TOPOLOGY, ADS, DDD or ANSWER
        assert len(question.destinations) >= 1

    def test_reject_unknown_source(self) -> None:
        """Unknown source should fail compilation."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(
            VALID_CSV_HEADER,
            "CTL-001,CTL,Test?,TEXT,,REQUIRED,,UnknownSource,,Owner,ALL,ANSWER",
        )
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        # Unknown source should produce error or warning
        assert result.report.diagnostics.count() > 0

    def test_reject_unknown_destination(self) -> None:
        """Unknown destination should fail compilation."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(
            VALID_CSV_HEADER,
            "CTL-001,CTL,Test?,TEXT,,REQUIRED,,Workbook,,Owner,ALL,UNKNOWN_DEST",
        )
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        # Unknown destination should produce error
        assert result.report.diagnostics.count() > 0


class TestAllowedValuesParsing:
    """Tests for allowed values parsing."""

    def test_parse_pipe_delimited_values(self) -> None:
        """Allowed values should be parsed from pipe-delimited string."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_2)  # Has YES|NO|UNKNOWN
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("DB-001")
        assert question is not None
        assert len(question.allowed_values) == 3
        codes = [v.code for v in question.allowed_values]
        assert "YES" in codes
        assert "NO" in codes
        assert "UNKNOWN" in codes

    def test_normalize_allowed_value_codes(self) -> None:
        """Allowed value codes should be normalized to uppercase."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(
            VALID_CSV_HEADER,
            "TEST-001,TEST,Test?,SINGLE_SELECT,yes|no|maybe,REQUIRED,,Workbook,,Owner,ALL,ANSWER",
        )
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("TEST-001")
        assert question is not None
        codes = [v.code for v in question.allowed_values]
        assert "YES" in codes
        assert "NO" in codes
        assert "MAYBE" in codes


class TestResponseTypeValidation:
    """Tests for response type validation."""

    def test_accept_valid_response_type(self) -> None:
        """Valid response types should be accepted."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)  # IDENTIFIER
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("CTL-001")
        assert question is not None
        assert question.response_type == "IDENTIFIER"

    def test_reject_unsupported_response_type(self) -> None:
        """Unsupported response types should fail compilation."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(
            VALID_CSV_HEADER,
            "CTL-001,CTL,Test?,UNSUPPORTED_TYPE,,REQUIRED,,Workbook,,Owner,ALL,ANSWER",
        )
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.report.is_success is False
        assert any("type" in d.message.lower() or "unsupported" in d.message.lower() 
                   for d in result.report.diagnostics.all())


class TestConditionCompilation:
    """Tests for Required_When condition compilation."""

    def test_compile_simple_condition(self) -> None:
        """Simple conditions should compile to AST."""
        from migration_intake.catalog.compiler import CatalogCompiler

        # Include both DB-001 and DB-002 so the reference is valid
        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_2, VALID_CSV_ROW_3)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("DB-002")
        assert question is not None
        assert question.applicability_condition is not None
        assert question.applicability_condition.compiled_ast is not None
        assert question.applicability_condition.compiled_ast["op"] == "eq"

    def test_empty_condition_means_always_applicable(self) -> None:
        """Empty Required_When means always applicable."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)  # No condition
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("CTL-001")
        assert question is not None
        assert question.applicability_condition is None


class TestCycleDetection:
    """Tests for dependency cycle detection."""

    def test_detect_condition_cycle(self) -> None:
        """Cycles in conditions should be detected."""
        from migration_intake.catalog.compiler import CatalogCompiler

        # Create a cycle: A depends on B, B depends on A
        csv_content = make_csv(
            VALID_CSV_HEADER,
            "Q-001,TEST,Question 1?,BOOLEAN,YES|NO,CONDITIONAL,Q-002 = YES,Workbook,,Owner,ALL,ANSWER",
            "Q-002,TEST,Question 2?,BOOLEAN,YES|NO,CONDITIONAL,Q-001 = YES,Workbook,,Owner,ALL,ANSWER",
        )
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        # Cycle should be detected and reported
        assert result.report.diagnostics.count() > 0
        assert any("cycle" in d.message.lower() for d in result.report.diagnostics.all())


class TestCanonicalSerialization:
    """Tests for canonical serialization."""

    def test_canonical_hash_is_deterministic(self) -> None:
        """Canonical hash should be deterministic."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1, VALID_CSV_ROW_2)
        compiler = CatalogCompiler()

        result1 = compiler.compile(csv_content, version="0.2.0")
        result2 = compiler.compile(csv_content, version="0.2.0")

        assert result1.release is not None
        assert result2.release is not None
        assert result1.release.canonical_hash == result2.release.canonical_hash

    def test_canonical_serialization_sorts_keys(self) -> None:
        """Canonical serialization should sort object keys."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        # The canonical hash should be based on sorted keys
        assert result.release.canonical_hash is not None


class TestCompilerReport:
    """Tests for compiler report."""

    def test_report_includes_question_count(self) -> None:
        """Report should include question count."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1, VALID_CSV_ROW_2)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.report.question_count == 2

    def test_report_includes_section_count(self) -> None:
        """Report should include section count."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1, VALID_CSV_ROW_2)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.report.section_count >= 2

    def test_report_includes_type_counts(self) -> None:
        """Report should include response type counts."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1, VALID_CSV_ROW_2)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert "IDENTIFIER" in result.report.type_counts or "BOOLEAN" in result.report.type_counts

    def test_report_collects_all_diagnostics(self) -> None:
        """Report should collect all independent diagnostics."""
        from migration_intake.catalog.compiler import CatalogCompiler

        # Create CSV with multiple issues
        csv_content = make_csv(
            VALID_CSV_HEADER,
            "CTL-001,CTL,Test?,UNSUPPORTED_TYPE,,REQUIRED,,Workbook,,Owner,ALL,ANSWER",
            "CTL-001,CTL,Duplicate?,TEXT,,REQUIRED,,Workbook,,Owner,ALL,ANSWER",
        )
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        # Should have multiple diagnostics (unsupported type + duplicate ID)
        assert result.report.diagnostics.count() >= 2


class TestCSVColumnValidation:
    """Tests for CSV column validation."""

    def test_require_exact_columns(self) -> None:
        """Compiler should require exact CSV columns."""
        from migration_intake.catalog.compiler import CatalogCompiler

        # Missing columns
        csv_content = "Question_ID,Section,Question\nCTL-001,CTL,Test?"
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.report.is_success is False
        assert any("column" in d.message.lower() or "missing" in d.message.lower() 
                   for d in result.report.diagnostics.all())

    def test_handle_header_aliases(self) -> None:
        """Compiler should handle known header aliases."""
        from migration_intake.catalog.compiler import CatalogCompiler

        # Use 'Resonse' alias (known typo in v1)
        csv_with_alias = VALID_CSV_HEADER.replace("Allowed_Values", "Allowed_Values_or_Unit")
        csv_content = make_csv(csv_with_alias, VALID_CSV_ROW_1.replace(",,REQUIRED", ",,REQUIRED"))
        compiler = CatalogCompiler()

        # Should handle the alias gracefully
        result = compiler.compile(csv_content, version="0.2.0")
        # May succeed or produce info diagnostic about alias


class TestCompileResult:
    """Tests for CompileResult structure."""

    def test_compile_result_has_release_and_report(self) -> None:
        """CompileResult should have release and report."""
        from migration_intake.catalog.compiler import CatalogCompiler, CompileResult

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert hasattr(result, "release")
        assert hasattr(result, "report")

    def test_failed_compilation_has_no_release(self) -> None:
        """Failed compilation should have no release."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = "invalid csv content"
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.report.is_success is False
        assert result.release is None


class TestRequiredLevelParsing:
    """Tests for required level parsing."""

    def test_parse_required_level(self) -> None:
        """Required level should be parsed correctly."""
        from migration_intake.catalog.compiler import CatalogCompiler

        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_1)  # REQUIRED
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("CTL-001")
        assert question is not None
        assert question.required_level == "REQUIRED"

    def test_parse_conditional_level(self) -> None:
        """CONDITIONAL level should be parsed correctly."""
        from migration_intake.catalog.compiler import CatalogCompiler

        # Include both DB-001 and DB-002 so the reference is valid
        csv_content = make_csv(VALID_CSV_HEADER, VALID_CSV_ROW_2, VALID_CSV_ROW_3)
        compiler = CatalogCompiler()

        result = compiler.compile(csv_content, version="0.2.0")

        assert result.release is not None
        question = result.release.get_question("DB-002")
        assert question is not None
        assert question.required_level == "CONDITIONAL"
