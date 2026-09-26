"""
Domain layer for Migration Intake.

This package contains pure domain logic with no external dependencies
on frameworks (Pydantic, SQLAlchemy, FastAPI, etc.).

Modules:
- ids: UUID-backed identity types
- states: State enumerations and transition policies
- errors: Domain-specific error types
- values: Value objects for normalization and validation
"""

from migration_intake.domain.errors import (
    DomainError,
    InvalidStateTransitionError,
    ValidationError,
)
from migration_intake.domain.ids import (
    ActorId,
    ApplicationId,
    CatalogReleaseId,
    ExternalIdentifier,
    ExternalIdType,
    IntakeId,
)
from migration_intake.domain.states import (
    ActorType,
    AnswerApplicability,
    AnswerReviewState,
    AnswerValueState,
    ApplicationState,
    CandidateState,
    EvidenceState,
    IntakeState,
)
from migration_intake.domain.values import (
    ControlCode,
    NormalizedAcronym,
    NormalizedName,
    SafeDecimal,
    UtcTimestamp,
    VersionToken,
)

__all__ = [
    # IDs
    "ApplicationId",
    "IntakeId",
    "CatalogReleaseId",
    "ActorId",
    "ExternalIdentifier",
    "ExternalIdType",
    # States
    "ApplicationState",
    "IntakeState",
    "AnswerApplicability",
    "AnswerValueState",
    "AnswerReviewState",
    "CandidateState",
    "EvidenceState",
    "ActorType",
    # Values
    "NormalizedName",
    "NormalizedAcronym",
    "SafeDecimal",
    "UtcTimestamp",
    "VersionToken",
    "ControlCode",
    # Errors
    "DomainError",
    "ValidationError",
    "InvalidStateTransitionError",
]
