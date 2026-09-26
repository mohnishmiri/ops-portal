"""
Safe condition AST for applicability conditions.

This module provides a constrained condition language for evaluating
question applicability. It compiles prose expressions to a safe JSON AST
and evaluates them against answer values.

Key constraints:
- No Python eval() or exec()
- No SQL fragments
- No arbitrary code execution
- Only supported operators
- Three-valued logic: TRUE, FALSE, UNKNOWN
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Supported operators
SUPPORTED_OPS = frozenset([
    "eq",       # Equal
    "ne",       # Not equal
    "in",       # In list
    "not_in",   # Not in list
    "contains", # Contains value
    "answered", # Has any answer
    "known",    # Has non-UNKNOWN answer
    "not",      # Logical NOT
    "all",      # Logical AND (all conditions)
    "any",      # Logical OR (any condition)
])


@dataclass(frozen=True)
class CompileResult:
    """
    Result of compiling a condition expression.

    Attributes:
        success: Whether compilation succeeded
        ast: Compiled AST if successful
        errors: List of error messages if failed
        is_pending: Whether the expression is unresolved prose
        raw_expression: Original expression text
    """

    success: bool
    ast: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    is_pending: bool = False
    raw_expression: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    """
    Result of evaluating a condition.

    Three-valued logic:
    - value=True, is_unknown=False: TRUE
    - value=False, is_unknown=False: FALSE
    - value=None, is_unknown=True: UNKNOWN

    Attributes:
        value: Boolean value or None for UNKNOWN
        is_unknown: Whether the result is UNKNOWN
    """

    value: bool | None
    is_unknown: bool = False

    def is_true(self) -> bool:
        """Check if result is TRUE."""
        return self.value is True and not self.is_unknown

    def is_false(self) -> bool:
        """Check if result is FALSE."""
        return self.value is False and not self.is_unknown

    def blocks_readiness(self) -> bool:
        """Check if this result blocks required-readiness.

        UNKNOWN blocks readiness because we can't determine applicability.
        TRUE and FALSE do not block (either applicable or not applicable).
        """
        return self.is_unknown


class ConditionCompiler:
    """
    Compiles condition expressions to safe AST.

    Supports:
    - Simple comparisons: Q-001 = YES, Q-001 != NO
    - List operations: Q-001 IN (A, B), Q-001 NOT IN (A, B)
    - Contains: Q-001 CONTAINS value
    - State checks: Q-001 IS ANSWERED, Q-001 IS KNOWN
    - Logical: NOT (expr), expr AND expr, expr OR expr
    - Registered prose mappings
    """

    def __init__(self) -> None:
        self._mappings: dict[str, dict[str, Any]] = {}

    def register_mapping(self, prose: str, ast: dict[str, Any]) -> None:
        """Register a prose-to-AST mapping."""
        self._mappings[prose.lower().strip()] = ast

    def compile(self, expression: str) -> CompileResult:
        """Compile an expression to AST."""
        if not expression or not expression.strip():
            return CompileResult(
                success=False,
                errors=["Empty expression"],
                raw_expression=expression,
            )

        expr = expression.strip()

        # Check for registered mappings first
        mapping = self._mappings.get(expr.lower())
        if mapping is not None:
            return CompileResult(success=True, ast=mapping, raw_expression=expr)

        # Check for dangerous patterns
        if self._is_dangerous(expr):
            return CompileResult(
                success=False,
                errors=["Expression contains forbidden patterns (Python/SQL)"],
                raw_expression=expr,
            )

        # Try to parse the expression
        try:
            ast = self._parse(expr)
            if ast is not None:
                return CompileResult(success=True, ast=ast, raw_expression=expr)
        except ValueError as e:
            return CompileResult(
                success=False,
                errors=[str(e)],
                raw_expression=expr,
            )

        # If we can't parse it, mark as pending (unresolved prose)
        return CompileResult(
            success=False,
            errors=[f"Unresolved prose expression: {expr}"],
            is_pending=True,
            raw_expression=expr,
        )

    def _is_dangerous(self, expr: str) -> bool:
        """Check for dangerous patterns."""
        lower = expr.lower()

        # Python patterns
        if any(p in lower for p in ["eval(", "exec(", "import ", "__", "lambda"]):
            return True

        # SQL patterns
        if any(p in lower for p in ["select ", "insert ", "update ", "delete ", "drop "]):
            return True

        return False

    def _parse(self, expr: str) -> dict[str, Any] | None:
        """Parse expression to AST."""
        expr = expr.strip()

        # Handle AND/OR at top level
        and_result = self._try_parse_binary(expr, " AND ", "all")
        if and_result is not None:
            return and_result

        or_result = self._try_parse_binary(expr, " OR ", "any")
        if or_result is not None:
            return or_result

        # Handle NOT
        if expr.upper().startswith("NOT "):
            inner = expr[4:].strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1].strip()
            inner_ast = self._parse(inner)
            if inner_ast is not None:
                return {"op": "not", "operand": inner_ast}

        # Handle parentheses
        if expr.startswith("(") and expr.endswith(")"):
            return self._parse(expr[1:-1].strip())

        # Handle simple comparisons
        return self._parse_simple(expr)

    def _try_parse_binary(
        self, expr: str, separator: str, op: str
    ) -> dict[str, Any] | None:
        """Try to parse a binary expression (AND/OR)."""
        # Simple split - doesn't handle nested parens perfectly
        # but works for common cases
        upper = expr.upper()
        if separator not in upper:
            return None

        # Find separator not inside parentheses
        depth = 0
        sep_len = len(separator)
        for i in range(len(expr) - sep_len + 1):
            if expr[i] == "(":
                depth += 1
            elif expr[i] == ")":
                depth -= 1
            elif depth == 0 and expr[i:i + sep_len].upper() == separator:
                left = expr[:i].strip()
                right = expr[i + sep_len:].strip()
                left_ast = self._parse(left)
                right_ast = self._parse(right)
                if left_ast is not None and right_ast is not None:
                    return {"op": op, "conditions": [left_ast, right_ast]}
                return None

        return None

    def _parse_simple(self, expr: str) -> dict[str, Any] | None:
        """Parse a simple expression."""
        upper = expr.upper()

        # IS ANSWERED
        match = re.match(r"^([A-Z0-9_-]+)\s+IS\s+ANSWERED$", upper)
        if match:
            return {"op": "answered", "question": match.group(1)}

        # IS KNOWN
        match = re.match(r"^([A-Z0-9_-]+)\s+IS\s+KNOWN$", upper)
        if match:
            return {"op": "known", "question": match.group(1)}

        # NOT IN
        match = re.match(r"^([A-Z0-9_-]+)\s+NOT\s+IN\s*\(([^)]+)\)$", upper)
        if match:
            question = match.group(1)
            values = [v.strip() for v in match.group(2).split(",")]
            return {"op": "not_in", "question": question, "values": values}

        # IN
        match = re.match(r"^([A-Z0-9_-]+)\s+IN\s*\(([^)]+)\)$", upper)
        if match:
            question = match.group(1)
            values = [v.strip() for v in match.group(2).split(",")]
            return {"op": "in", "question": question, "values": values}

        # CONTAINS
        match = re.match(r"^([A-Z0-9_-]+)\s+CONTAINS\s+(\S+)$", upper)
        if match:
            return {"op": "contains", "question": match.group(1), "value": match.group(2)}

        # != (not equal)
        match = re.match(r"^([A-Z0-9_-]+)\s*!=\s*(\S+)$", upper)
        if match:
            return {"op": "ne", "question": match.group(1), "value": match.group(2)}

        # = (equal)
        match = re.match(r"^([A-Z0-9_-]+)\s*=\s*(\S+)$", upper)
        if match:
            return {"op": "eq", "question": match.group(1), "value": match.group(2)}

        return None


class ConditionEvaluator:
    """
    Evaluates condition AST against answer values.

    Implements three-valued logic where UNKNOWN is distinct from FALSE.
    """

    def evaluate(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate an AST against answer values."""
        op = ast.get("op")

        if op == "eq":
            return self._eval_eq(ast, answers)
        elif op == "ne":
            return self._eval_ne(ast, answers)
        elif op == "in":
            return self._eval_in(ast, answers)
        elif op == "not_in":
            return self._eval_not_in(ast, answers)
        elif op == "contains":
            return self._eval_contains(ast, answers)
        elif op == "answered":
            return self._eval_answered(ast, answers)
        elif op == "known":
            return self._eval_known(ast, answers)
        elif op == "not":
            return self._eval_not(ast, answers)
        elif op == "all":
            return self._eval_all(ast, answers)
        elif op == "any":
            return self._eval_any(ast, answers)
        else:
            # Unknown operator - treat as UNKNOWN
            return EvaluationResult(value=None, is_unknown=True)

    def _get_answer(
        self, question: str, answers: dict[str, Any]
    ) -> tuple[str | None, bool]:
        """Get answer value and whether it exists."""
        if question not in answers:
            return None, False
        return str(answers[question]), True

    def _eval_eq(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate eq operator."""
        question = ast["question"]
        expected = ast["value"]
        actual, exists = self._get_answer(question, answers)

        if not exists:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=actual == expected, is_unknown=False)

    def _eval_ne(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate ne operator."""
        question = ast["question"]
        expected = ast["value"]
        actual, exists = self._get_answer(question, answers)

        if not exists:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=actual != expected, is_unknown=False)

    def _eval_in(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate in operator."""
        question = ast["question"]
        values = ast["values"]
        actual, exists = self._get_answer(question, answers)

        if not exists:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=actual in values, is_unknown=False)

    def _eval_not_in(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate not_in operator."""
        question = ast["question"]
        values = ast["values"]
        actual, exists = self._get_answer(question, answers)

        if not exists:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=actual not in values, is_unknown=False)

    def _eval_contains(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate contains operator."""
        question = ast["question"]
        value = ast["value"]
        actual, exists = self._get_answer(question, answers)

        if not exists:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=value in actual, is_unknown=False)

    def _eval_answered(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate answered operator."""
        question = ast["question"]
        _, exists = self._get_answer(question, answers)

        # answered is deterministic - no UNKNOWN
        return EvaluationResult(value=exists, is_unknown=False)

    def _eval_known(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate known operator."""
        question = ast["question"]
        actual, exists = self._get_answer(question, answers)

        if not exists:
            return EvaluationResult(value=False, is_unknown=False)

        # UNKNOWN value means not known
        return EvaluationResult(value=actual != "UNKNOWN", is_unknown=False)

    def _eval_not(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate not operator."""
        operand = ast["operand"]
        result = self.evaluate(operand, answers)

        if result.is_unknown:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=not result.value, is_unknown=False)

    def _eval_all(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate all (AND) operator.

        Three-valued AND:
        - If any is FALSE, result is FALSE
        - If none is FALSE but some is UNKNOWN, result is UNKNOWN
        - If all are TRUE, result is TRUE
        """
        conditions = ast["conditions"]
        has_unknown = False

        for cond in conditions:
            result = self.evaluate(cond, answers)
            if result.is_false():
                return EvaluationResult(value=False, is_unknown=False)
            if result.is_unknown:
                has_unknown = True

        if has_unknown:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=True, is_unknown=False)

    def _eval_any(
        self, ast: dict[str, Any], answers: dict[str, Any]
    ) -> EvaluationResult:
        """Evaluate any (OR) operator.

        Three-valued OR:
        - If any is TRUE, result is TRUE
        - If none is TRUE but some is UNKNOWN, result is UNKNOWN
        - If all are FALSE, result is FALSE
        """
        conditions = ast["conditions"]
        has_unknown = False

        for cond in conditions:
            result = self.evaluate(cond, answers)
            if result.is_true():
                return EvaluationResult(value=True, is_unknown=False)
            if result.is_unknown:
                has_unknown = True

        if has_unknown:
            return EvaluationResult(value=None, is_unknown=True)

        return EvaluationResult(value=False, is_unknown=False)


class CycleDetector:
    """
    Detects dependency cycles in condition references.

    Uses depth-first search to find strongly connected components.
    """

    def detect(self, dependencies: dict[str, list[str]]) -> list[list[str]]:
        """Detect cycles in dependency graph.

        Args:
            dependencies: Map of question ID to list of questions it depends on

        Returns:
            List of cycles found (each cycle is a list of question IDs)
        """
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in dependencies.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)

            path.pop()
            rec_stack.remove(node)

        for node in dependencies:
            if node not in visited:
                dfs(node)

        return cycles


class ASTValidator:
    """
    Validates condition AST structure.
    """

    def validate(self, ast: dict[str, Any]) -> list[str]:
        """Validate AST structure.

        Returns list of error messages (empty if valid).
        """
        errors: list[str] = []

        if "op" not in ast:
            errors.append("AST missing required 'op' field")
            return errors

        op = ast["op"]
        if op not in SUPPORTED_OPS:
            errors.append(f"Unknown operator: {op}")
            return errors

        # Validate operator-specific requirements
        if op in ("eq", "ne"):
            if "question" not in ast:
                errors.append(f"{op} operator requires 'question' field")
            if "value" not in ast:
                errors.append(f"{op} operator requires 'value' field")

        elif op in ("in", "not_in"):
            if "question" not in ast:
                errors.append(f"{op} operator requires 'question' field")
            if "values" not in ast:
                errors.append(f"{op} operator requires 'values' field")
            elif not isinstance(ast.get("values"), list):
                errors.append(f"{op} operator 'values' must be a list")

        elif op == "contains":
            if "question" not in ast:
                errors.append(f"{op} operator requires 'question' field")
            if "value" not in ast:
                errors.append(f"{op} operator requires 'value' field")

        elif op in ("answered", "known"):
            if "question" not in ast:
                errors.append(f"{op} operator requires 'question' field")

        elif op == "not":
            if "operand" not in ast:
                errors.append("not operator requires 'operand' field")
            elif isinstance(ast.get("operand"), dict):
                errors.extend(self.validate(ast["operand"]))

        elif op in ("all", "any"):
            if "conditions" not in ast:
                errors.append(f"{op} operator requires 'conditions' field")
            elif not isinstance(ast.get("conditions"), list):
                errors.append(f"{op} operator 'conditions' must be a list")
            else:
                for i, cond in enumerate(ast["conditions"]):
                    if isinstance(cond, dict):
                        cond_errors = self.validate(cond)
                        for e in cond_errors:
                            errors.append(f"conditions[{i}]: {e}")
                    else:
                        errors.append(f"conditions[{i}]: must be an object")

        return errors
