"""
Persistence layer for Migration Intake.

Provides the SQLAlchemy engine factory, session factory, portable column
type definitions, repositories, and the Unit of Work.  All ORM models must
use the portable types from this package to ensure identical behaviour on
SQLite (development) and Oracle (production).

Public API surface:
- create_engine_from_url: engine factory with dialect-appropriate listeners
- create_session_factory: sessionmaker bound to an engine
- redact_url: safe URL string for logging (credentials removed)
- SQLITE_BUSY_TIMEOUT_MS: advisory timeout constant for SQLite
- PortableUUID, PortableUTC, PortableDecimal, CanonicalJSON, Sha256Hex
- UnitOfWork, uow_context: transactional Unit of Work
- ApplicationRepository, CatalogRepository, IntakeRepository, AnswerRepository
- EvidenceRepository, WaveUtilRepository, ImportRepository
"""

from __future__ import annotations

from migration_intake.persistence.database import (
    SQLITE_BUSY_TIMEOUT_MS,
    create_engine_from_url,
    create_session_factory,
    redact_url,
)
from migration_intake.persistence.repositories import (
    AnswerRepository,
    ApplicationRepository,
    CatalogRepository,
    EvidenceRepository,
    ImportRepository,
    IntakeRepository,
    WaveUtilRepository,
)
from migration_intake.persistence.types import (
    CanonicalJSON,
    PortableDecimal,
    PortableUTC,
    PortableUUID,
    Sha256Hex,
)
from migration_intake.persistence.unit_of_work import UnitOfWork, uow_context

__all__ = [
    # Engine / session
    "SQLITE_BUSY_TIMEOUT_MS",
    "create_engine_from_url",
    "create_session_factory",
    "redact_url",
    # Portable types
    "CanonicalJSON",
    "PortableDecimal",
    "PortableUTC",
    "PortableUUID",
    "Sha256Hex",
    # Unit of Work
    "UnitOfWork",
    "uow_context",
    # Repositories
    "AnswerRepository",
    "ApplicationRepository",
    "CatalogRepository",
    "EvidenceRepository",
    "ImportRepository",
    "IntakeRepository",
    "WaveUtilRepository",
]
