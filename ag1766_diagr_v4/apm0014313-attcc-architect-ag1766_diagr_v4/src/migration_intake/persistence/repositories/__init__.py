"""
Repository implementations for persistence layer.

Repositories provide a collection-like interface for domain aggregates,
abstracting the underlying storage mechanism.
"""

from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.persistence.repositories.imports import ImportRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.persistence.repositories.interfaces import InterfaceRepository
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository

__all__ = [
    "AnswerRepository",
    "ApplicationRepository",
    "CandidateRepository",
    "CatalogRepository",
    "EvidenceRepository",
    "ImportRepository",
    "IntakeRepository",
    "InterfaceRepository",
    "SnapshotRepository",
    "WaveUtilRepository",
]
