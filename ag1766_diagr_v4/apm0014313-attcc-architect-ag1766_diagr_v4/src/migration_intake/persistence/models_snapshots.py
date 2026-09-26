"""
ORM model classes for snapshots — P07 (Snapshot Persistence).

Design rules:
- Snapshots are immutable once created.
- Database constraints prevent update/delete through normal application paths.
- A frozen intake points to its snapshot/hash and cannot accept mutations.

Minimum snapshot fields:
- ID (UUID)
- Unique intake ID (FK)
- Catalog release ID/hash
- Schema version
- Canonical JSON
- SHA-256 hash
- Actor (created_by)
- UTC creation time
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)

from migration_intake.persistence.naming import Base
from migration_intake.persistence.types import (
    PortableUTC,
    PortableUUID,
    Sha256Hex,
)

__all__ = [
    "IntakeSnapshot",
]


# ─────────────────────────────────────────────────────────────────────────────
# intake_snapshots
# ─────────────────────────────────────────────────────────────────────────────


class IntakeSnapshot(Base):
    """
    An immutable snapshot of a frozen intake.

    Table: ``int_snaps``
    PK auto-name: ``pk_int_snaps`` (12 chars ✓)

    Invariants:
    - Once created, snapshots are never updated or deleted.
    - The canonical_json field contains the complete serialized intake state.
    - The sha256_hex is the hash of canonical_json bytes.
    - Each intake can have at most one snapshot (enforced by unique constraint).
    """

    __tablename__ = "int_snaps"

    # Primary key
    id: Any = Column(PortableUUID(), primary_key=True)

    # Foreign keys
    intake_id: Any = Column(PortableUUID(), nullable=False)
    catalog_id: Any = Column(PortableUUID(), nullable=False)
    created_by_id: Any = Column(PortableUUID(), nullable=False)

    # Snapshot metadata
    schema_version: Any = Column(String(32), nullable=False)
    catalog_sha256: Any = Column(Sha256Hex(), nullable=False)

    # Canonical payload
    canonical_json: Any = Column(Text(), nullable=False)
    sha256_hex: Any = Column(Sha256Hex(), nullable=False)

    # Timestamps
    created_at: Any = Column(PortableUTC(), nullable=False)

    # Constraints
    # use_alter=True on all FKs so metadata.create_all() can determine a valid
    # creation order regardless of import order between model modules.
    __table_args__ = (
        # Each intake can have at most one snapshot
        UniqueConstraint("intake_id", name="uq_snap_intake"),
        # FK to intakes
        ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_snap_int",
            use_alter=True,
        ),
        # FK to catalog_releases
        ForeignKeyConstraint(
            ["catalog_id"],
            ["cat_releases.id"],
            name="fk_snap_cat",
            use_alter=True,
        ),
        # FK to actors
        ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_snap_act",
            use_alter=True,
        ),
        # Index for lookup by hash
        Index("ix_snap_hash", "sha256_hex"),
    )
