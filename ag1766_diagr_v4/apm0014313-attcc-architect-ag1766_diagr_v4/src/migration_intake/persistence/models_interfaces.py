"""
ORM model — interface register (single canonical table, current-state only).

Table: ``interfaces`` — one row per counterpart interface for an
application, capturing all 33 columns of the App Data Capture workbook's
Interface sheet verbatim. No revision history is kept; ``updated_at``/
``updated_by_id`` record the most recent write (import acceptance or manual
edit) and ``row_version`` provides optimistic concurrency control.

Two identifiers for the migrating application, serving different purposes:
- ``application_id`` — internal FK to ``applications.id``, ``ON DELETE
  CASCADE``. Never shown to a user; exists purely so deleting an
  application (via any path, ORM or raw SQL) automatically removes its
  interfaces rows too, without every future deletion path needing to
  remember this table.
- ``migrating_app_correlation_id`` — the sheet's own "Migrating App
  Correlation ID" value (e.g. "18678"), stored verbatim. This is the
  business-facing identifier used for sheet-row validation and display, per
  explicit product decision (not a native Oracle FK — a filtered-composite
  reference to ``app_identifiers`` where ``identifier_type='CORRELATION'``
  isn't expressible).

No uniqueness is enforced on the natural key: the source sheet can contain
multiple distinct rows sharing the same ``interface_correlation_id`` (see
``InterfaceRepository.find_exact_duplicate`` for de-dup, which compares
every field, not just the key).

Design rules (identical to models.py / models_evidence.py):
- UUIDs as PortableUUID, timestamps as PortableUTC — same type conventions.
- All constraint names ≤ 30 characters (Oracle 12c conservative limit).

Constraint names
----------------
fk_irec_appl  (12) — application_id → applications.id (ON DELETE CASCADE)
fk_irec_cact  (12) — created_by_id → actors.id
fk_irec_uact  (12) — updated_by_id → actors.id
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)

from migration_intake.persistence.naming import Base
from migration_intake.persistence.types import PortableUTC, PortableUUID

__all__ = ["InterfaceRecord"]


class InterfaceRecord(Base):
    """
    One counterpart interface (directional connection) for an application.

    Table: ``interfaces``
    PK auto-name:  ``pk_interfaces``     (13 chars ✓)
    FK explicit:   ``fk_irec_appl``, ``fk_irec_cact``, ``fk_irec_uact``
    """

    __tablename__ = "interfaces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["application_id"], ["applications.id"], name="fk_irec_appl",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["created_by_id"], ["actors.id"], name="fk_irec_cact"),
        ForeignKeyConstraint(["updated_by_id"], ["actors.id"], name="fk_irec_uact"),
        Index("ix_irec_app_state_id", "application_id", "state", "id"),
    )

    id: Any = Column(PortableUUID(), primary_key=True)

    # Internal FK — cascade-delete plumbing only, never user-facing.
    application_id: Any = Column(PortableUUID(), nullable=False)

    # Business-facing identity of the migrating application (not applications.id).
    migrating_app_correlation_id: Any = Column(String(255), nullable=False)
    migrating_app_acronym: Any = Column(String(255), nullable=True)
    consumer_or_provider: Any = Column(String(64), nullable=True)

    # Natural key (as captured on the sheet / entered by a reviewer) —
    # not unique; see module docstring.
    interface_correlation_id: Any = Column(String(255), nullable=False)

    # The remaining 30 Interface-sheet columns, all captured verbatim.
    interface_app_acronym: Any = Column(String(255), nullable=True)
    interface_migration_wave: Any = Column(String(255), nullable=True)
    interface_system_location: Any = Column(String(255), nullable=True)
    end_point_name: Any = Column(Text(), nullable=True)
    data_traffic_direction: Any = Column(String(32), nullable=True)  # Inbound | Outbound
    connection_owner: Any = Column(String(255), nullable=True)
    sync_async: Any = Column(String(32), nullable=True)
    current_protocol: Any = Column(String(255), nullable=True)
    current_interface_type: Any = Column(String(255), nullable=True)
    target_protocol: Any = Column(String(255), nullable=True)
    target_interface_type: Any = Column(String(255), nullable=True)
    interface_impact_change_type: Any = Column(String(255), nullable=True)
    current_port: Any = Column(String(32), nullable=True)
    future_port: Any = Column(String(32), nullable=True)
    encrypted_solution_cloud: Any = Column(String(16), nullable=True)  # Yes | No
    low_latency_required: Any = Column(String(16), nullable=True)  # Yes | No
    throughput_volume_req: Any = Column(String(255), nullable=True)
    att_architecture_validated: Any = Column(String(16), nullable=True)  # Yes | No
    listed_in_itap: Any = Column(String(32), nullable=True)
    engagement_email_sent_on: Any = Column(String(64), nullable=True)
    funding_template_sent: Any = Column(String(64), nullable=True)
    interface_commitment_date: Any = Column(String(64), nullable=True)
    interface_included_in_crp: Any = Column(String(255), nullable=True)
    funding_approved_epic: Any = Column(String(32), nullable=True)
    connectivity_tested: Any = Column(String(16), nullable=True)  # Yes | No
    uat_tested: Any = Column(String(32), nullable=True)
    interface_contact: Any = Column(Text(), nullable=True)
    interface_cutover_contact: Any = Column(Text(), nullable=True)
    notes: Any = Column(Text(), nullable=True)

    state: Any = Column(String(30), nullable=False, default="ACTIVE")
    origin: Any = Column(String(16), nullable=False, default="MANUAL")  # IMPORT | MANUAL

    created_at: Any = Column(PortableUTC(), nullable=False)
    created_by_id: Any = Column(PortableUUID(), nullable=False)
    updated_at: Any = Column(PortableUTC(), nullable=False)
    updated_by_id: Any = Column(PortableUUID(), nullable=False)
    row_version: Any = Column(Integer(), nullable=False, default=1)

