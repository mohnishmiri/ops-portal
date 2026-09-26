"""
Response types package.

This package contains the response type registry and all 25 response
type implementations organized by group:
- scalar: BOOLEAN, SINGLE_SELECT, TEXT, LONG_TEXT, IDENTIFIER
- collections: MULTI_SELECT, TEXT_PAIR, COUNT_PAIR, CONTROLLED_PAIR, PEOPLE_LIST
- measurements: MEASUREMENT, MEASUREMENT_PAIR, MEASUREMENT_SET, MEASUREMENT_CONTEXT
- decisions: BOOLEAN_WITH_RATIONALE, CONTROLLED_SET, SINGLE_SELECT_PER_COMPONENT,
             DECISION_WITH_PERSON, APPROVAL
- computed: REGISTER_STATUS, VALIDATION_RESULT, ISSUE_REGISTER, DECISION_REGISTER,
            APPROVAL_REGISTER, EVIDENCE_REFERENCE
"""

from typing import Optional

from migration_intake.catalog.response_types.base import (
    ComparisonResult,
    ParseResult,
    ResponseType,
    ResponseTypeBase,
    ResponseTypeCodes,
    ValidationResult,
)

# Collection types (R02)
from migration_intake.catalog.response_types.collections import (
    ControlledPairType,
    CountPairType,
    MultiSelectType,
    PeopleListType,
    TextPairType,
)

# Computed types (R05)
from migration_intake.catalog.response_types.computed import (
    ApprovalRegisterType,
    DecisionRegisterType,
    EvidenceReferenceType,
    IssueRegisterType,
    RegisterStatusType,
    ValidationResultType,
)

# Decision types (R04)
from migration_intake.catalog.response_types.decisions import (
    ApprovalType,
    BooleanWithRationaleType,
    ControlledSetType,
    DecisionWithPersonType,
    SingleSelectPerComponentType,
)

# Measurement types (R03)
from migration_intake.catalog.response_types.measurements import (
    MeasurementContextType,
    MeasurementPairType,
    MeasurementSetType,
    MeasurementType,
)
from migration_intake.catalog.response_types.registry import ResponseTypeRegistry

# Scalar types (R01)
from migration_intake.catalog.response_types.scalar import (
    BooleanType,
    BooleanValue,
    IdentifierType,
    IdentifierTypeCodes,
    LongTextType,
    SingleSelectType,
    TextType,
)

# Singleton for default registry
_default_registry: ResponseTypeRegistry | None = None


def get_default_registry() -> ResponseTypeRegistry:
    """
    Get the default registry with all 25 response types registered.

    This is a singleton - the same registry instance is returned on each call.

    Returns:
        ResponseTypeRegistry with all types registered
    """
    global _default_registry

    if _default_registry is None:
        _default_registry = _create_default_registry()

    return _default_registry


def _create_default_registry() -> ResponseTypeRegistry:
    """Create a new registry with all 25 response types."""
    registry = ResponseTypeRegistry()

    # Register scalar types (R01) - 5 types
    registry.register(BooleanType())
    registry.register(SingleSelectType())
    registry.register(TextType())
    registry.register(LongTextType())
    registry.register(IdentifierType())

    # Register collection types (R02) - 5 types
    registry.register(MultiSelectType())
    registry.register(TextPairType())
    registry.register(CountPairType())
    registry.register(ControlledPairType())
    registry.register(PeopleListType())

    # Register measurement types (R03) - 4 types
    registry.register(MeasurementType())
    registry.register(MeasurementPairType())
    registry.register(MeasurementSetType())
    registry.register(MeasurementContextType())

    # Register decision types (R04) - 5 types
    registry.register(BooleanWithRationaleType())
    registry.register(ControlledSetType())
    registry.register(SingleSelectPerComponentType())
    registry.register(DecisionWithPersonType())
    registry.register(ApprovalType())

    # Register computed types (R05) - 6 types
    registry.register(RegisterStatusType())
    registry.register(ValidationResultType())
    registry.register(IssueRegisterType())
    registry.register(DecisionRegisterType())
    registry.register(ApprovalRegisterType())
    registry.register(EvidenceReferenceType())

    return registry


__all__ = [
    # Base classes and protocols
    "ResponseType",
    "ResponseTypeBase",
    "ResponseTypeCodes",
    "ResponseTypeRegistry",
    "ParseResult",
    "ValidationResult",
    "ComparisonResult",
    # Registry factory
    "get_default_registry",
    # Scalar types (R01)
    "BooleanType",
    "BooleanValue",
    "SingleSelectType",
    "TextType",
    "LongTextType",
    "IdentifierType",
    "IdentifierTypeCodes",
    # Collection types (R02)
    "MultiSelectType",
    "TextPairType",
    "CountPairType",
    "ControlledPairType",
    "PeopleListType",
    # Measurement types (R03)
    "MeasurementType",
    "MeasurementPairType",
    "MeasurementSetType",
    "MeasurementContextType",
    # Decision types (R04)
    "BooleanWithRationaleType",
    "ControlledSetType",
    "SingleSelectPerComponentType",
    "DecisionWithPersonType",
    "ApprovalType",
    # Computed types (R05)
    "RegisterStatusType",
    "ValidationResultType",
    "IssueRegisterType",
    "DecisionRegisterType",
    "ApprovalRegisterType",
    "EvidenceReferenceType",
]
