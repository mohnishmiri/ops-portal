"""
Tests for safe condition AST.

These tests verify:
- Compile supported expressions (eq, ne, in, not_in, etc.)
- Reject prose/unresolved references/operators
- Detect dependency cycles
- Evaluate true/false/unknown
- Unknown does not become false
- No Python/SQL expression execution
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest


class TestConditionOperators:
    """Tests for supported condition operators."""

    def test_eq_operator_compiles(self) -> None:
        """eq operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("DB-001 = YES")

        assert result.success is True
        assert result.ast is not None
        assert result.ast["op"] == "eq"
        assert result.ast["question"] == "DB-001"
        assert result.ast["value"] == "YES"

    def test_ne_operator_compiles(self) -> None:
        """ne operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("DB-001 != YES")

        assert result.success is True
        assert result.ast["op"] == "ne"

    def test_in_operator_compiles(self) -> None:
        """in operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("APP-004 IN (CRITICAL, HIGH)")

        assert result.success is True
        assert result.ast["op"] == "in"
        assert result.ast["question"] == "APP-004"
        assert result.ast["values"] == ["CRITICAL", "HIGH"]

    def test_not_in_operator_compiles(self) -> None:
        """not_in operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("APP-004 NOT IN (LOW, UNKNOWN)")

        assert result.success is True
        assert result.ast["op"] == "not_in"

    def test_contains_operator_compiles(self) -> None:
        """contains operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("NET-001 CONTAINS VPN")

        assert result.success is True
        assert result.ast["op"] == "contains"

    def test_answered_operator_compiles(self) -> None:
        """answered operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("DB-001 IS ANSWERED")

        assert result.success is True
        assert result.ast["op"] == "answered"
        assert result.ast["question"] == "DB-001"

    def test_known_operator_compiles(self) -> None:
        """known operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("DB-001 IS KNOWN")

        assert result.success is True
        assert result.ast["op"] == "known"

    def test_not_operator_compiles(self) -> None:
        """not operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("NOT (DB-001 = YES)")

        assert result.success is True
        assert result.ast["op"] == "not"
        assert result.ast["operand"]["op"] == "eq"

    def test_all_operator_compiles(self) -> None:
        """all (AND) operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("DB-001 = YES AND BAT-001 = YES")

        assert result.success is True
        assert result.ast["op"] == "all"
        assert len(result.ast["conditions"]) == 2

    def test_any_operator_compiles(self) -> None:
        """any (OR) operator should compile to AST."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("DB-001 = YES OR BAT-001 = YES")

        assert result.success is True
        assert result.ast["op"] == "any"
        assert len(result.ast["conditions"]) == 2


class TestConditionCompileResult:
    """Tests for CompileResult structure."""

    def test_compile_result_success(self) -> None:
        """CompileResult should indicate success."""
        from migration_intake.catalog.conditions import CompileResult

        result = CompileResult(
            success=True,
            ast={"op": "eq", "question": "DB-001", "value": "YES"},
        )

        assert result.success is True
        assert result.ast is not None
        assert result.errors == []

    def test_compile_result_failure(self) -> None:
        """CompileResult should indicate failure with errors."""
        from migration_intake.catalog.conditions import CompileResult

        result = CompileResult(
            success=False,
            errors=["Unresolved reference: UNKNOWN-001"],
        )

        assert result.success is False
        assert result.ast is None
        assert len(result.errors) == 1

    def test_compile_result_is_pending(self) -> None:
        """CompileResult should support pending status."""
        from migration_intake.catalog.conditions import CompileResult

        result = CompileResult(
            success=False,
            is_pending=True,
            raw_expression="Dependencies exist",
        )

        assert result.is_pending is True


class TestConditionRejection:
    """Tests for rejecting invalid conditions."""

    def test_reject_unresolved_prose(self) -> None:
        """Unresolved prose should be rejected."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("Dependencies exist")

        assert result.success is False
        assert result.is_pending is True
        assert "unresolved" in result.errors[0].lower() or "pending" in result.errors[0].lower()

    def test_reject_unknown_operator(self) -> None:
        """Unknown operators should be rejected."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("DB-001 LIKE YES")

        assert result.success is False
        # Unknown operators result in unresolved prose (pending)
        assert result.is_pending is True or len(result.errors) > 0

    def test_reject_python_expression(self) -> None:
        """Python expressions should be rejected."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("eval('DB-001')")

        assert result.success is False

    def test_reject_sql_fragment(self) -> None:
        """SQL fragments should be rejected."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("SELECT * FROM answers WHERE question_id = 'DB-001'")

        assert result.success is False

    def test_reject_empty_expression(self) -> None:
        """Empty expressions should be rejected."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("")

        assert result.success is False

    def test_reject_whitespace_only(self) -> None:
        """Whitespace-only expressions should be rejected."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("   ")

        assert result.success is False


class TestConditionEvaluation:
    """Tests for condition evaluation."""

    def test_evaluate_eq_true(self) -> None:
        """eq should evaluate to TRUE when values match."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "eq", "question": "DB-001", "value": "YES"}
        answers = {"DB-001": "YES"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_eq_false(self) -> None:
        """eq should evaluate to FALSE when values don't match."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "eq", "question": "DB-001", "value": "YES"}
        answers = {"DB-001": "NO"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False

    def test_evaluate_eq_unknown_when_unanswered(self) -> None:
        """eq should evaluate to UNKNOWN when question is unanswered."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "eq", "question": "DB-001", "value": "YES"}
        answers: Dict[str, Any] = {}

        result = evaluator.evaluate(ast, answers)

        assert result.value is None  # None represents UNKNOWN
        assert result.is_unknown is True

    def test_evaluate_ne_true(self) -> None:
        """ne should evaluate to TRUE when values don't match."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "ne", "question": "DB-001", "value": "YES"}
        answers = {"DB-001": "NO"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_in_true(self) -> None:
        """in should evaluate to TRUE when value is in list."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "in", "question": "APP-004", "values": ["CRITICAL", "HIGH"]}
        answers = {"APP-004": "CRITICAL"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_in_false(self) -> None:
        """in should evaluate to FALSE when value is not in list."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "in", "question": "APP-004", "values": ["CRITICAL", "HIGH"]}
        answers = {"APP-004": "LOW"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False

    def test_evaluate_not_in_true(self) -> None:
        """not_in should evaluate to TRUE when value is not in list."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "not_in", "question": "APP-004", "values": ["LOW", "UNKNOWN"]}
        answers = {"APP-004": "CRITICAL"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_answered_true(self) -> None:
        """answered should evaluate to TRUE when question has answer."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "answered", "question": "DB-001"}
        answers = {"DB-001": "YES"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_answered_false(self) -> None:
        """answered should evaluate to FALSE when question has no answer."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "answered", "question": "DB-001"}
        answers: Dict[str, Any] = {}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False

    def test_evaluate_known_true(self) -> None:
        """known should evaluate to TRUE when answer is not UNKNOWN."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "known", "question": "DB-001"}
        answers = {"DB-001": "YES"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_known_false_for_unknown_value(self) -> None:
        """known should evaluate to FALSE when answer is UNKNOWN."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "known", "question": "DB-001"}
        answers = {"DB-001": "UNKNOWN"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False

    def test_evaluate_not_inverts_true(self) -> None:
        """not should invert TRUE to FALSE."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "not", "operand": {"op": "eq", "question": "DB-001", "value": "YES"}}
        answers = {"DB-001": "YES"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False

    def test_evaluate_not_inverts_false(self) -> None:
        """not should invert FALSE to TRUE."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "not", "operand": {"op": "eq", "question": "DB-001", "value": "YES"}}
        answers = {"DB-001": "NO"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_not_preserves_unknown(self) -> None:
        """not should preserve UNKNOWN."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "not", "operand": {"op": "eq", "question": "DB-001", "value": "YES"}}
        answers: Dict[str, Any] = {}

        result = evaluator.evaluate(ast, answers)

        assert result.is_unknown is True

    def test_evaluate_all_true(self) -> None:
        """all should evaluate to TRUE when all conditions are TRUE."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {
            "op": "all",
            "conditions": [
                {"op": "eq", "question": "DB-001", "value": "YES"},
                {"op": "eq", "question": "BAT-001", "value": "YES"},
            ],
        }
        answers = {"DB-001": "YES", "BAT-001": "YES"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_all_false_when_one_false(self) -> None:
        """all should evaluate to FALSE when any condition is FALSE."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {
            "op": "all",
            "conditions": [
                {"op": "eq", "question": "DB-001", "value": "YES"},
                {"op": "eq", "question": "BAT-001", "value": "YES"},
            ],
        }
        answers = {"DB-001": "YES", "BAT-001": "NO"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False

    def test_evaluate_all_unknown_when_none_false_but_some_unknown(self) -> None:
        """all should evaluate to UNKNOWN when no FALSE but some UNKNOWN."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {
            "op": "all",
            "conditions": [
                {"op": "eq", "question": "DB-001", "value": "YES"},
                {"op": "eq", "question": "BAT-001", "value": "YES"},
            ],
        }
        answers = {"DB-001": "YES"}  # BAT-001 is unanswered

        result = evaluator.evaluate(ast, answers)

        assert result.is_unknown is True

    def test_evaluate_any_true(self) -> None:
        """any should evaluate to TRUE when any condition is TRUE."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {
            "op": "any",
            "conditions": [
                {"op": "eq", "question": "DB-001", "value": "YES"},
                {"op": "eq", "question": "BAT-001", "value": "YES"},
            ],
        }
        answers = {"DB-001": "NO", "BAT-001": "YES"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True

    def test_evaluate_any_false_when_all_false(self) -> None:
        """any should evaluate to FALSE when all conditions are FALSE."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {
            "op": "any",
            "conditions": [
                {"op": "eq", "question": "DB-001", "value": "YES"},
                {"op": "eq", "question": "BAT-001", "value": "YES"},
            ],
        }
        answers = {"DB-001": "NO", "BAT-001": "NO"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False

    def test_evaluate_any_unknown_when_none_true_but_some_unknown(self) -> None:
        """any should evaluate to UNKNOWN when no TRUE but some UNKNOWN."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {
            "op": "any",
            "conditions": [
                {"op": "eq", "question": "DB-001", "value": "YES"},
                {"op": "eq", "question": "BAT-001", "value": "YES"},
            ],
        }
        answers = {"DB-001": "NO"}  # BAT-001 is unanswered

        result = evaluator.evaluate(ast, answers)

        assert result.is_unknown is True


class TestUnknownSemantics:
    """Tests for UNKNOWN semantics - unknown does not become false."""

    def test_unknown_is_not_false(self) -> None:
        """UNKNOWN should not be treated as FALSE."""
        from migration_intake.catalog.conditions import EvaluationResult

        unknown = EvaluationResult(value=None, is_unknown=True)
        false_result = EvaluationResult(value=False, is_unknown=False)

        assert unknown.is_unknown is True
        assert false_result.is_unknown is False
        assert unknown != false_result

    def test_unknown_blocks_required_readiness(self) -> None:
        """UNKNOWN should block required-readiness checks."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "eq", "question": "DB-001", "value": "YES"}
        answers: Dict[str, Any] = {}

        result = evaluator.evaluate(ast, answers)

        # UNKNOWN means we can't determine if condition is met
        assert result.is_unknown is True
        assert result.blocks_readiness() is True

    def test_true_does_not_block_readiness(self) -> None:
        """TRUE should not block required-readiness."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "eq", "question": "DB-001", "value": "YES"}
        answers = {"DB-001": "YES"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is True
        assert result.blocks_readiness() is False

    def test_false_does_not_block_readiness(self) -> None:
        """FALSE should not block required-readiness (question not applicable)."""
        from migration_intake.catalog.conditions import ConditionEvaluator

        evaluator = ConditionEvaluator()
        ast = {"op": "eq", "question": "DB-001", "value": "YES"}
        answers = {"DB-001": "NO"}

        result = evaluator.evaluate(ast, answers)

        assert result.value is False
        assert result.blocks_readiness() is False


class TestCycleDetection:
    """Tests for dependency cycle detection."""

    def test_detect_direct_cycle(self) -> None:
        """Direct self-reference should be detected."""
        from migration_intake.catalog.conditions import CycleDetector

        detector = CycleDetector()
        dependencies = {
            "Q-001": ["Q-001"],  # Self-reference
        }

        cycles = detector.detect(dependencies)

        assert len(cycles) > 0
        assert "Q-001" in cycles[0]

    def test_detect_indirect_cycle(self) -> None:
        """Indirect cycle should be detected."""
        from migration_intake.catalog.conditions import CycleDetector

        detector = CycleDetector()
        dependencies = {
            "Q-001": ["Q-002"],
            "Q-002": ["Q-003"],
            "Q-003": ["Q-001"],  # Cycle back to Q-001
        }

        cycles = detector.detect(dependencies)

        assert len(cycles) > 0

    def test_no_cycle_in_dag(self) -> None:
        """DAG should have no cycles."""
        from migration_intake.catalog.conditions import CycleDetector

        detector = CycleDetector()
        dependencies = {
            "Q-001": ["Q-002", "Q-003"],
            "Q-002": ["Q-004"],
            "Q-003": ["Q-004"],
            "Q-004": [],
        }

        cycles = detector.detect(dependencies)

        assert len(cycles) == 0

    def test_multiple_cycles_detected(self) -> None:
        """Multiple independent cycles should be detected."""
        from migration_intake.catalog.conditions import CycleDetector

        detector = CycleDetector()
        dependencies = {
            "Q-001": ["Q-002"],
            "Q-002": ["Q-001"],  # Cycle 1
            "Q-003": ["Q-004"],
            "Q-004": ["Q-003"],  # Cycle 2
        }

        cycles = detector.detect(dependencies)

        assert len(cycles) >= 2


class TestConditionMappings:
    """Tests for prose-to-AST mappings."""

    def test_register_mapping(self) -> None:
        """Prose mappings should be registerable."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        compiler.register_mapping(
            "Dependencies exist",
            {"op": "answered", "question": "DEP-001"},
        )

        result = compiler.compile("Dependencies exist")

        assert result.success is True
        assert result.ast["op"] == "answered"

    def test_unregistered_prose_is_pending(self) -> None:
        """Unregistered prose should be marked as pending."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        result = compiler.compile("Some unknown condition")

        assert result.success is False
        assert result.is_pending is True

    def test_case_insensitive_mapping(self) -> None:
        """Prose mappings should be case-insensitive."""
        from migration_intake.catalog.conditions import ConditionCompiler

        compiler = ConditionCompiler()
        compiler.register_mapping(
            "Dependencies exist",
            {"op": "answered", "question": "DEP-001"},
        )

        result = compiler.compile("DEPENDENCIES EXIST")

        assert result.success is True


class TestEvaluationResult:
    """Tests for EvaluationResult structure."""

    def test_evaluation_result_true(self) -> None:
        """EvaluationResult should represent TRUE."""
        from migration_intake.catalog.conditions import EvaluationResult

        result = EvaluationResult(value=True, is_unknown=False)

        assert result.value is True
        assert result.is_unknown is False
        assert result.is_true() is True
        assert result.is_false() is False

    def test_evaluation_result_false(self) -> None:
        """EvaluationResult should represent FALSE."""
        from migration_intake.catalog.conditions import EvaluationResult

        result = EvaluationResult(value=False, is_unknown=False)

        assert result.value is False
        assert result.is_unknown is False
        assert result.is_true() is False
        assert result.is_false() is True

    def test_evaluation_result_unknown(self) -> None:
        """EvaluationResult should represent UNKNOWN."""
        from migration_intake.catalog.conditions import EvaluationResult

        result = EvaluationResult(value=None, is_unknown=True)

        assert result.value is None
        assert result.is_unknown is True
        assert result.is_true() is False
        assert result.is_false() is False


class TestASTValidation:
    """Tests for AST validation."""

    def test_validate_valid_ast(self) -> None:
        """Valid AST should pass validation."""
        from migration_intake.catalog.conditions import ASTValidator

        validator = ASTValidator()
        ast = {"op": "eq", "question": "DB-001", "value": "YES"}

        errors = validator.validate(ast)

        assert len(errors) == 0

    def test_validate_missing_op(self) -> None:
        """AST without op should fail validation."""
        from migration_intake.catalog.conditions import ASTValidator

        validator = ASTValidator()
        ast = {"question": "DB-001", "value": "YES"}

        errors = validator.validate(ast)

        assert len(errors) > 0
        assert any("op" in e.lower() for e in errors)

    def test_validate_unknown_op(self) -> None:
        """AST with unknown op should fail validation."""
        from migration_intake.catalog.conditions import ASTValidator

        validator = ASTValidator()
        ast = {"op": "unknown_op", "question": "DB-001"}

        errors = validator.validate(ast)

        assert len(errors) > 0

    def test_validate_eq_requires_question_and_value(self) -> None:
        """eq op should require question and value."""
        from migration_intake.catalog.conditions import ASTValidator

        validator = ASTValidator()
        ast = {"op": "eq", "question": "DB-001"}  # Missing value

        errors = validator.validate(ast)

        assert len(errors) > 0
        assert any("value" in e.lower() for e in errors)

    def test_validate_in_requires_values_list(self) -> None:
        """in op should require values list."""
        from migration_intake.catalog.conditions import ASTValidator

        validator = ASTValidator()
        ast = {"op": "in", "question": "APP-004", "value": "CRITICAL"}  # Should be values

        errors = validator.validate(ast)

        assert len(errors) > 0

    def test_validate_nested_ast(self) -> None:
        """Nested AST should be validated recursively."""
        from migration_intake.catalog.conditions import ASTValidator

        validator = ASTValidator()
        ast = {
            "op": "all",
            "conditions": [
                {"op": "eq", "question": "DB-001", "value": "YES"},
                {"op": "invalid"},  # Invalid nested AST
            ],
        }

        errors = validator.validate(ast)

        assert len(errors) > 0
