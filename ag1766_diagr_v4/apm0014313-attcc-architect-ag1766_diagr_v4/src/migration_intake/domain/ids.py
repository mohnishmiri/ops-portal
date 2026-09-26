"""
UUID-backed identity types for domain entities.

Each entity type has its own ID class to prevent accidental mixing
of IDs across entity boundaries. IDs are immutable and hashable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class ApplicationId:
    """Unique identifier for an Application entity."""

    value: uuid.UUID

    def __init__(self, value: str | uuid.UUID) -> None:
        if value is None:
            raise ValueError("ApplicationId cannot be None")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("ApplicationId cannot be empty")
            try:
                parsed = uuid.UUID(value)
            except (ValueError, AttributeError) as e:
                raise ValueError(f"Invalid UUID format: {value}") from e
            object.__setattr__(self, "value", parsed)
        elif isinstance(value, uuid.UUID):
            object.__setattr__(self, "value", value)
        else:
            raise TypeError(f"Expected str or UUID, got {type(value)}")

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"ApplicationId({self.value})"

    @classmethod
    def generate(cls) -> ApplicationId:
        """Generate a new unique ApplicationId."""
        return cls(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class IntakeId:
    """Unique identifier for an Intake entity."""

    value: uuid.UUID

    def __init__(self, value: str | uuid.UUID) -> None:
        if value is None:
            raise ValueError("IntakeId cannot be None")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("IntakeId cannot be empty")
            try:
                parsed = uuid.UUID(value)
            except (ValueError, AttributeError) as e:
                raise ValueError(f"Invalid UUID format: {value}") from e
            object.__setattr__(self, "value", parsed)
        elif isinstance(value, uuid.UUID):
            object.__setattr__(self, "value", value)
        else:
            raise TypeError(f"Expected str or UUID, got {type(value)}")

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"IntakeId({self.value})"

    @classmethod
    def generate(cls) -> IntakeId:
        """Generate a new unique IntakeId."""
        return cls(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class CatalogReleaseId:
    """Unique identifier for a CatalogRelease entity."""

    value: uuid.UUID

    def __init__(self, value: str | uuid.UUID) -> None:
        if value is None:
            raise ValueError("CatalogReleaseId cannot be None")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("CatalogReleaseId cannot be empty")
            try:
                parsed = uuid.UUID(value)
            except (ValueError, AttributeError) as e:
                raise ValueError(f"Invalid UUID format: {value}") from e
            object.__setattr__(self, "value", parsed)
        elif isinstance(value, uuid.UUID):
            object.__setattr__(self, "value", value)
        else:
            raise TypeError(f"Expected str or UUID, got {type(value)}")

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"CatalogReleaseId({self.value})"

    @classmethod
    def generate(cls) -> CatalogReleaseId:
        """Generate a new unique CatalogReleaseId."""
        return cls(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class ActorId:
    """Unique identifier for an Actor (user or system)."""

    value: uuid.UUID

    def __init__(self, value: str | uuid.UUID) -> None:
        if value is None:
            raise ValueError("ActorId cannot be None")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("ActorId cannot be empty")
            try:
                parsed = uuid.UUID(value)
            except (ValueError, AttributeError) as e:
                raise ValueError(f"Invalid UUID format: {value}") from e
            object.__setattr__(self, "value", parsed)
        elif isinstance(value, uuid.UUID):
            object.__setattr__(self, "value", value)
        else:
            raise TypeError(f"Expected str or UUID, got {type(value)}")

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"ActorId({self.value})"

    @classmethod
    def generate(cls) -> ActorId:
        """Generate a new unique ActorId."""
        return cls(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class AnswerId:
    """Unique identifier for an Answer entity."""

    value: uuid.UUID

    def __init__(self, value: str | uuid.UUID) -> None:
        if value is None:
            raise ValueError("AnswerId cannot be None")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("AnswerId cannot be empty")
            try:
                parsed = uuid.UUID(value)
            except (ValueError, AttributeError) as e:
                raise ValueError(f"Invalid UUID format: {value}") from e
            object.__setattr__(self, "value", parsed)
        elif isinstance(value, uuid.UUID):
            object.__setattr__(self, "value", value)
        else:
            raise TypeError(f"Expected str or UUID, got {type(value)}")

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> AnswerId:
        """Generate a new unique AnswerId."""
        return cls(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class EvidenceId:
    """Unique identifier for an Evidence entity."""

    value: uuid.UUID

    def __init__(self, value: str | uuid.UUID) -> None:
        if value is None:
            raise ValueError("EvidenceId cannot be None")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("EvidenceId cannot be empty")
            try:
                parsed = uuid.UUID(value)
            except (ValueError, AttributeError) as e:
                raise ValueError(f"Invalid UUID format: {value}") from e
            object.__setattr__(self, "value", parsed)
        elif isinstance(value, uuid.UUID):
            object.__setattr__(self, "value", value)
        else:
            raise TypeError(f"Expected str or UUID, got {type(value)}")

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> EvidenceId:
        """Generate a new unique EvidenceId."""
        return cls(uuid.uuid4())


class ExternalIdType(Enum):
    """Types of external identifiers."""

    ITAP = "ITAP"
    MOTS = "MOTS"
    CORRELATION = "CORRELATION"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    """
    Typed external identifier (iTAP, MOTS, Correlation, etc.).

    External identifiers are stored separately from the internal UUID
    and maintain their original type for traceability.
    """

    id_type: ExternalIdType
    value: str

    def __init__(self, id_type: ExternalIdType, value: str) -> None:
        if not isinstance(id_type, ExternalIdType):
            raise TypeError(f"Expected ExternalIdType, got {type(id_type)}")

        normalized = value.strip() if value else ""
        if not normalized:
            raise ValueError("External identifier value cannot be empty")

        object.__setattr__(self, "id_type", id_type)
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return f"{self.id_type.value}:{self.value}"

    def __repr__(self) -> str:
        return f"ExternalIdentifier({self.id_type.value}, {self.value!r})"
