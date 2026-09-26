"""
Port definitions for infrastructure adapters.

Ports are narrow protocols that define the interface between the
application layer and infrastructure. They use only domain types
and DTOs, never infrastructure-specific types.

No SQLAlchemy, openpyxl, or httpx types appear in these protocols.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO, Protocol, runtime_checkable

from migration_intake.application.dto import StoredContent
from migration_intake.domain.ids import (
    ActorId,
    ApplicationId,
    CatalogReleaseId,
    EvidenceId,
    IntakeId,
)
from migration_intake.domain.states import ApplicationState, IntakeState
from migration_intake.domain.values import VersionToken

if TYPE_CHECKING:
    from datetime import datetime


# Repository protocols define data access patterns
# They return domain objects or DTOs, never ORM entities


@runtime_checkable
class ApplicationRepository(Protocol):
    """Repository for Application aggregate."""

    def get_by_id(self, id: ApplicationId) -> ApplicationData | None:
        """Get application by ID, or None if not found."""
        ...

    def get_by_external_id(
        self, id_type: str, value: str
    ) -> ApplicationData | None:
        """Get application by external identifier."""
        ...

    def exists(self, id: ApplicationId) -> bool:
        """Check if application exists."""
        ...

    def add(self, data: ApplicationData) -> None:
        """Add a new application."""
        ...

    def update(self, data: ApplicationData) -> None:
        """Update an existing application."""
        ...


@runtime_checkable
class IntakeRepository(Protocol):
    """Repository for Intake aggregate."""

    def get_by_id(self, id: IntakeId) -> IntakeData | None:
        """Get intake by ID, or None if not found."""
        ...

    def get_active_for_application(
        self, application_id: ApplicationId
    ) -> IntakeData | None:
        """Get the active intake for an application, if any."""
        ...

    def add(self, data: IntakeData) -> None:
        """Add a new intake."""
        ...

    def update(self, data: IntakeData) -> None:
        """Update an existing intake."""
        ...


@runtime_checkable
class CatalogRepository(Protocol):
    """Repository for CatalogRelease."""

    def get_by_id(self, id: CatalogReleaseId) -> CatalogReleaseData | None:
        """Get catalog release by ID."""
        ...

    def get_published(self, version: str) -> CatalogReleaseData | None:
        """Get published catalog release by version."""
        ...

    def get_latest_published(self) -> CatalogReleaseData | None:
        """Get the latest published catalog release."""
        ...


@runtime_checkable
class AuditRepository(Protocol):
    """Repository for audit events."""

    def add(self, event: AuditEventData) -> None:
        """Add an audit event."""
        ...


@runtime_checkable
class CandidateStagingPort(Protocol):
    """
    Port for staging AI-produced candidate proposals and findings.

    This port is intentionally candidate-only; implementations must never write
    canonical answers at this boundary.
    """

    def stage_mapping_batch(
        self,
        *,
        application_id: str,
        intake_id: str,
        evidence_item_id: str,
        import_run_id: str,
        origin: str,
        proposals: list[dict],
        findings: list[dict],
    ) -> None:
        """Persist one mapping batch of proposed candidates and findings."""
        ...


@runtime_checkable
class UnitOfWork(Protocol):
    """
    Unit of work for transactional consistency.

    Repositories share one transaction inside a unit of work.
    """

    @property
    def applications(self) -> ApplicationRepository:
        """Application repository."""
        ...

    @property
    def intakes(self) -> IntakeRepository:
        """Intake repository."""
        ...

    @property
    def catalogs(self) -> CatalogRepository:
        """Catalog repository."""
        ...

    @property
    def audits(self) -> AuditRepository:
        """Audit repository."""
        ...

    def commit(self) -> None:
        """Commit the transaction."""
        ...

    def rollback(self) -> None:
        """Rollback the transaction."""
        ...

    def __enter__(self) -> UnitOfWork:
        """Enter context manager."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager, rolling back on exception."""
        ...


@runtime_checkable
class EvidenceStore(Protocol):
    """
    Content-addressed storage for evidence files.

    Callers receive storage keys and hashes, never filesystem paths.
    """

    def put(
        self, stream: BinaryIO, expected_size: int | None = None
    ) -> StoredContent:
        """
        Store content and return storage metadata.

        Args:
            stream: Binary stream of content
            expected_size: Optional expected size for validation

        Returns:
            StoredContent with key, hash, and size
        """
        ...

    def open(self, storage_key: str) -> BinaryIO:
        """
        Open stored content for reading.

        Args:
            storage_key: Key returned from put()

        Returns:
            Binary stream of content
        """
        ...

    def exists(self, storage_key: str) -> bool:
        """Check if content exists."""
        ...


@runtime_checkable
class Clock(Protocol):
    """UTC clock for deterministic time in tests."""

    def now(self) -> datetime:
        """Return current UTC time."""
        ...


@runtime_checkable
class IdGenerator(Protocol):
    """ID generator for deterministic IDs in tests."""

    def generate_application_id(self) -> ApplicationId:
        """Generate a new ApplicationId."""
        ...

    def generate_intake_id(self) -> IntakeId:
        """Generate a new IntakeId."""
        ...

    def generate_evidence_id(self) -> EvidenceId:
        """Generate a new EvidenceId."""
        ...


# Data classes for repository operations
# These are simple containers, not domain entities


class ApplicationData:
    """Data container for application persistence."""

    def __init__(
        self,
        id: ApplicationId,
        name: str,
        acronym: str | None,
        state: ApplicationState,
        version: VersionToken,
        created_by: ActorId,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.name = name
        self.acronym = acronym
        self.state = state
        self.version = version
        self.created_by = created_by
        self.created_at = created_at
        self.updated_at = updated_at


class IntakeData:
    """Data container for intake persistence."""

    def __init__(
        self,
        id: IntakeId,
        application_id: ApplicationId,
        catalog_release_id: CatalogReleaseId,
        state: IntakeState,
        version: VersionToken,
        created_by: ActorId,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.application_id = application_id
        self.catalog_release_id = catalog_release_id
        self.state = state
        self.version = version
        self.created_by = created_by
        self.created_at = created_at
        self.updated_at = updated_at


class CatalogReleaseData:
    """Data container for catalog release persistence."""

    def __init__(
        self,
        id: CatalogReleaseId,
        version: str,
        published: bool,
        published_at: datetime | None,
    ) -> None:
        self.id = id
        self.version = version
        self.published = published
        self.published_at = published_at


class AuditEventData:
    """Data container for audit event persistence."""

    def __init__(
        self,
        event_id: str,
        occurred_at: datetime,
        actor_id: ActorId,
        actor_type: str,
        request_correlation_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict | None = None,
    ) -> None:
        self.event_id = event_id
        self.occurred_at = occurred_at
        self.actor_id = actor_id
        self.actor_type = actor_type
        self.request_correlation_id = request_correlation_id
        self.event_type = event_type
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.payload = payload
