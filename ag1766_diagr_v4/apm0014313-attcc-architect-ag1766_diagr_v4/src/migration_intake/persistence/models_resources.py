"""
ORM model classes for target resources — P5B (Resource Persistence).

Design rules (from P5A contract):
- Resources are append-only: never hard-delete after first revision
- Resource head stores current revision/state/concurrency metadata
- Revisions are immutable once created
- Parent links reference stable resource identities, not revisions
- Lifecycle transitions are explicit (ACTIVE → RETIRED/SUPERSEDED)

Table names:
- res_resources: Resource head (mutable state)
- res_revisions: Resource revisions (append-only)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from migration_intake.persistence.naming import Base
from migration_intake.persistence.types import (
    CanonicalJSON,
    PortableUTC,
    PortableUUID,
)

__all__ = [
    "TargetResource",
    "TargetResourceRevision",
    "TopologyResourceLink",
    "TopologyResourceLinkRevision",
]


# ─────────────────────────────────────────────────────────────────────────────
# Target Resources
# ─────────────────────────────────────────────────────────────────────────────


class TargetResource(Base):
    """
    Target resource head with current state.

    Table: ``res_resources``
    PK auto-name: ``pk_res_resources`` (15 chars ✓)

    The resource head stores:
    - Stable identity (id, logical_key, kind)
    - Current revision reference
    - Lifecycle state (ACTIVE, RETIRED, SUPERSEDED)
    - Concurrency control (revision_number)
    - Parent reference (stable identity, not revision)
    """

    __tablename__ = "res_resources"

    # Primary key
    id: Any = Column(PortableUUID(), primary_key=True)

    # Intake scope
    intake_id: Any = Column(PortableUUID(), nullable=False)

    # Resource identity
    logical_key: Any = Column(String(255), nullable=False)
    kind: Any = Column(String(32), nullable=False)
    scope_key: Any = Column(String(64), nullable=False)

    # Scope
    lifecycle: Any = Column(String(16), nullable=False)  # SOURCE | TARGET
    environment: Any = Column(String(16), nullable=True)  # DEV | TEST | STAGING | PROD
    site: Any = Column(String(64), nullable=True)
    tier: Any = Column(String(32), nullable=True)

    # Parent reference (stable identity)
    parent_id: Any = Column(PortableUUID(), nullable=True)

    # Current revision
    current_revision_id: Any = Column(PortableUUID(), nullable=True)
    revision_number: Any = Column(Integer, nullable=False, default=0)
    row_version: Any = Column(Integer, nullable=False, default=1)

    # Lifecycle state
    resource_state: Any = Column(String(16), nullable=False, default="ACTIVE")

    # Supersession
    successor_id: Any = Column(PortableUUID(), nullable=True)

    # Timestamps
    created_at: Any = Column(PortableUTC(), nullable=False)
    updated_at: Any = Column(PortableUTC(), nullable=False)

    # Audit
    created_by: Any = Column(String(255), nullable=False)

    __table_args__ = (
        # Unique logical key within intake scope
        UniqueConstraint(
            "intake_id",
            "logical_key",
            "lifecycle",
            "scope_key",
            name="uq_res_scope",
        ),
        # Foreign key to intake
        ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_res_intake",
        ),
        # Self-referential FK for parent
        ForeignKeyConstraint(
            ["parent_id"],
            ["res_resources.id"],
            name="fk_res_parent",
        ),
        # Self-referential FK for successor
        ForeignKeyConstraint(
            ["successor_id"],
            ["res_resources.id"],
            name="fk_res_successor",
        ),
        # Index for querying by intake
        Index("ix_res_intake", "intake_id"),
        # Index for querying by kind
        Index("ix_res_kind", "intake_id", "kind"),
        Index("ix_res_scope", "intake_id", "scope_key"),
        # Index for querying by parent
        Index("ix_res_parent", "parent_id"),
    )


class TargetResourceRevision(Base):
    """
    Immutable resource revision.

    Table: ``res_revisions``
    PK auto-name: ``pk_res_revisions`` (15 chars ✓)

    Revisions are append-only and immutable once created.
    Each revision captures:
    - Full payload at that point in time
    - Review state
    - Provenance references
    - Author and timestamp
    """

    __tablename__ = "res_revisions"

    # Primary key
    id: Any = Column(PortableUUID(), primary_key=True)

    # Resource reference
    resource_id: Any = Column(PortableUUID(), nullable=False)

    # Revision number (monotonically increasing per resource)
    revision_number: Any = Column(Integer, nullable=False)

    # Payload (kind-specific attributes)
    payload: Any = Column(CanonicalJSON(), nullable=False)

    # Review state
    review_state: Any = Column(String(16), nullable=False)  # PROPOSED | REVIEWED | CONFIRMED | REJECTED

    # Immutable relationship/lifecycle state at this revision
    parent_id: Any = Column(PortableUUID(), nullable=True)
    resource_state: Any = Column(String(16), nullable=False, default="ACTIVE")
    change_reason: Any = Column(String(255), nullable=True)

    # Provenance
    provenance_references: Any = Column(CanonicalJSON(), nullable=True)

    # Audit
    authored_at: Any = Column(PortableUTC(), nullable=False)
    authored_by: Any = Column(String(255), nullable=False)

    __table_args__ = (
        # Unique revision number per resource
        UniqueConstraint(
            "resource_id",
            "revision_number",
            name="uq_res_rev_num",
        ),
        # Foreign key to resource
        ForeignKeyConstraint(
            ["resource_id"],
            ["res_resources.id"],
            name="fk_rev_resource",
        ),
        ForeignKeyConstraint(
            ["parent_id"],
            ["res_resources.id"],
            name="fk_rev_parent",
        ),
        # Index for querying revisions by resource
        Index("ix_rev_resource", "resource_id"),
    )


class TopologyResourceLink(Base):
    """Mutable relationship head between stable resource identities."""

    __tablename__ = "res_links"

    id: Any = Column(PortableUUID(), primary_key=True)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    relationship_type: Any = Column(String(64), nullable=False)
    source_resource_id: Any = Column(PortableUUID(), nullable=False)
    target_resource_id: Any = Column(PortableUUID(), nullable=False)
    current_revision_id: Any = Column(PortableUUID(), nullable=True)
    revision_number: Any = Column(Integer, nullable=False, default=0)
    row_version: Any = Column(Integer, nullable=False, default=1)
    link_state: Any = Column(String(16), nullable=False, default="ACTIVE")
    created_at: Any = Column(PortableUTC(), nullable=False)
    updated_at: Any = Column(PortableUTC(), nullable=False)
    created_by: Any = Column(String(255), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_rlink_intake"),
        ForeignKeyConstraint(
            ["source_resource_id"], ["res_resources.id"], name="fk_rlink_source"
        ),
        ForeignKeyConstraint(
            ["target_resource_id"], ["res_resources.id"], name="fk_rlink_target"
        ),
        Index("ix_rlink_intake", "intake_id"),
        Index("ix_rlink_source", "source_resource_id"),
        Index("ix_rlink_target", "target_resource_id"),
        UniqueConstraint(
            "intake_id",
            "relationship_type",
            "source_resource_id",
            "target_resource_id",
            name="uq_rlink_identity",
        ),
    )


class TopologyResourceLinkRevision(Base):
    """Append-only revision for a typed resource relationship."""

    __tablename__ = "res_link_revisions"

    id: Any = Column(PortableUUID(), primary_key=True)
    link_id: Any = Column(PortableUUID(), nullable=False)
    revision_number: Any = Column(Integer, nullable=False)
    review_state: Any = Column(String(16), nullable=False)
    provenance_references: Any = Column(CanonicalJSON(), nullable=True)
    authored_at: Any = Column(PortableUTC(), nullable=False)
    authored_by: Any = Column(String(255), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["link_id"], ["res_links.id"], name="fk_rlrev_link"
        ),
        UniqueConstraint("link_id", "revision_number", name="uq_rlrev_num"),
        Index("ix_rlrev_link", "link_id"),
    )
