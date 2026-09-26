"""
Application layer for Migration Intake.

This package contains application services, commands, queries, DTOs,
and port definitions. It coordinates use cases without containing
domain logic or infrastructure concerns.

Canonical modules (G1):
- commands: All command objects for state-changing operations
- dto: ActorContext and other data transfer objects
- ports: Protocol definitions for infrastructure adapters
- queries: Query objects and read DTOs
"""

from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
    IdentifierInput,
    UpdateApplicationIdentityCommand,
)
from migration_intake.application.dto import ActorContext
from migration_intake.application.ports import (
    ApplicationRepository,
    CatalogRepository,
    EvidenceStore,
    IntakeRepository,
    UnitOfWork,
)
from migration_intake.application.queries import (
    ApplicationSummaryDTO,
    IntakeSummaryDTO,
)

__all__ = [
    # DTOs
    "ActorContext",
    "ApplicationSummaryDTO",
    "IntakeSummaryDTO",
    # Commands
    "CreateApplicationCommand",
    "CreateIntakeCommand",
    "IdentifierInput",
    "UpdateApplicationIdentityCommand",
    # Ports
    "UnitOfWork",
    "ApplicationRepository",
    "IntakeRepository",
    "CatalogRepository",
    "EvidenceStore",
]
