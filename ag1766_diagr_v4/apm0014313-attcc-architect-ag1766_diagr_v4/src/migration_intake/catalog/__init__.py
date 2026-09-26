"""
Catalog package for Migration Intake.

This package contains catalog definitions, response type registry,
diagnostics, and the catalog compiler.
"""

from migration_intake.catalog.compiler import (
    CatalogCompiler,
)
from migration_intake.catalog.compiler import (
    CompileResult as CatalogCompileResult,
)
from migration_intake.catalog.conditions import (
    ASTValidator,
    CompileResult,
    ConditionCompiler,
    ConditionEvaluator,
    CycleDetector,
    EvaluationResult,
)
from migration_intake.catalog.definitions import (
    AllowedValue,
    ApplicabilityCondition,
    CatalogRelease,
    CollectionMode,
    DestinationMapping,
    OwnerRelationship,
    QuestionDefinition,
    RequiredLevel,
    Section,
    SourceRelationship,
)
from migration_intake.catalog.diagnostics import (
    CompilerReport,
    Diagnostic,
    DiagnosticCodes,
    DiagnosticCollector,
    DiagnosticSeverity,
)
from migration_intake.catalog.response_types.base import (
    ComparisonResult,
    ParseResult,
    ResponseTypeBase,
    ResponseTypeCodes,
    ValidationResult,
)
from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

__all__ = [
    # Definitions
    "CatalogRelease",
    "Section",
    "QuestionDefinition",
    "AllowedValue",
    "ApplicabilityCondition",
    "SourceRelationship",
    "OwnerRelationship",
    "DestinationMapping",
    "RequiredLevel",
    "CollectionMode",
    # Diagnostics
    "DiagnosticSeverity",
    "DiagnosticCodes",
    "Diagnostic",
    "DiagnosticCollector",
    "CompilerReport",
    # Conditions
    "ConditionCompiler",
    "ConditionEvaluator",
    "CompileResult",
    "EvaluationResult",
    "CycleDetector",
    "ASTValidator",
    # Compiler
    "CatalogCompiler",
    "CatalogCompileResult",
    # Response Types
    "ResponseTypeRegistry",
    "ResponseTypeBase",
    "ResponseTypeCodes",
    "ParseResult",
    "ValidationResult",
    "ComparisonResult",
]
