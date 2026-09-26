"""
Domain-specific error types.

These errors represent domain rule violations and should be caught
and translated at application/web boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from migration_intake.domain.states import ApplicationState, IntakeState


class DomainError(Exception):
    """Base class for domain errors."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__


class ValidationError(DomainError):
    """Raised when a value fails domain validation."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}", code="VALIDATION_ERROR")
        self.field = field


class InvalidStateTransitionError(DomainError):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        entity_type: str,
        from_state: ApplicationState | IntakeState | str,
        to_state: ApplicationState | IntakeState | str,
    ) -> None:
        message = (
            f"Invalid {entity_type} state transition: "
            f"{from_state} -> {to_state}"
        )
        super().__init__(message, code="INVALID_STATE_TRANSITION")
        self.entity_type = entity_type
        self.from_state = from_state
        self.to_state = to_state


class ConcurrencyError(DomainError):
    """Raised when optimistic concurrency check fails."""

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        expected_version: int,
        actual_version: int,
    ) -> None:
        message = (
            f"Concurrency conflict on {entity_type} {entity_id}: "
            f"expected version {expected_version}, found {actual_version}"
        )
        super().__init__(message, code="CONCURRENCY_CONFLICT")
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class NotFoundError(DomainError):
    """Raised when a required entity is not found."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        message = f"{entity_type} not found: {entity_id}"
        super().__init__(message, code="NOT_FOUND")
        self.entity_type = entity_type
        self.entity_id = entity_id


class DuplicateError(DomainError):
    """Raised when a duplicate entity would be created."""

    def __init__(self, entity_type: str, identifier: str) -> None:
        message = f"Duplicate {entity_type}: {identifier}"
        super().__init__(message, code="DUPLICATE")
        self.entity_type = entity_type
        self.identifier = identifier


class AuthorizationError(DomainError):
    """Raised when an actor lacks required capability."""

    def __init__(self, capability: str, resource: str | None = None) -> None:
        if resource:
            message = f"Missing capability '{capability}' for resource '{resource}'"
        else:
            message = f"Missing capability '{capability}'"
        super().__init__(message, code="AUTHORIZATION_ERROR")
        self.capability = capability
        self.resource = resource
