"""
ORM model classes — P05 (Evidence and WaveUtil Persistence).

Three new tables supplementing the 12 core tables in models.py:
  evidence_items       — uploaded evidence files attached to an intake
  wave_util_rows       — one row per discovered server (append-only revisions)
  wave_util_revisions  — revision snapshots of a wave_util_rows row

Design rules (identical to models.py):
- Do NOT edit models.py; extend via this separate module imported alongside it.
- Circular FK: wave_util_rows.current_rev_id → wave_util_revisions.id is broken
  with use_alter=True (same pattern as ans_instances / ans_revisions in models.py).
- All constraint names ≤ 30 characters (Oracle 12c conservative limit).
- All column names ≤ 30 characters.
- UUIDs as PortableUUID, timestamps as PortableUTC, JSON as CanonicalJSON,
  SHA-256 as Sha256Hex — identical type conventions to models.py.
- Python-side defaults (default=) match the existing models.py convention.

Constraint names
----------------
evidence_items FKs:
  fk_evid_appl  (12) — application_id → applications.id
  fk_evid_intk  (12) — intake_id → intakes.id
  fk_evid_act   (11) — created_by_id → actors.id

wave_util_rows FKs / UQs:
  uq_wrow_app_norm  (16) — (application_id, normalized_server_name)
  fk_wrow_appl      (12) — application_id → applications.id
  fk_wrow_intk      (12) — intake_id → intakes.id
  fk_wrow_act       (11) — created_by_id → actors.id
  fk_wrow_wrev      (12) — current_rev_id → wave_util_revisions.id [use_alter]

wave_util_revisions FKs:
  fk_wrev_wrow  (12) — row_id → wave_util_rows.id
  fk_wrev_act   (11) — authored_by_id → actors.id
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)

from migration_intake.persistence.naming import Base
from migration_intake.persistence.types import (
    CanonicalJSON,
    PortableUTC,
    PortableUUID,
    Sha256Hex,
)

__all__ = [
    "EvidenceItem",
    "WaveUtilRevision",
    "WaveUtilRow",
]


# ─────────────────────────────────────────────────────────────────────────────
# evidence_items
# ─────────────────────────────────────────────────────────────────────────────


class EvidenceItem(Base):
    """
    An uploaded evidence file associated with an application (and optionally
    an intake).

    Table: ``evidence_items``
    PK auto-name:  ``pk_evidence_items``          (17 chars ✓)
    UQ explicit:   ``uq_evid_app_intake_storage`` (26 chars ✓)
    FK explicit:   ``fk_evid_appl``               (12 chars ✓)
    FK explicit:   ``fk_evid_intk``               (12 chars ✓)
    FK explicit:   ``fk_evid_act``                (11 chars ✓)
    """

    __tablename__ = "evidence_items"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "intake_id",
            "storage_key",
            name="uq_evid_app_intake_storage",
        ),
        # FK: evidence_items.application_id → applications.id
        ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_evid_appl",
        ),
        # FK: evidence_items.intake_id → intakes.id  (nullable — evidence can
        # exist before an intake is opened)
        ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_evid_intk",
        ),
        # FK: evidence_items.created_by_id → actors.id
        ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_evid_act",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=True)
    storage_key: Any = Column(String(100), nullable=False)
    sha256_hex: Any = Column(Sha256Hex(), nullable=False)
    size_bytes: Any = Column(BigInteger(), nullable=False)
    media_type: Any = Column(
        String(80), nullable=False, default="application/octet-stream"
    )
    original_filename: Any = Column(String(500), nullable=True)
    state: Any = Column(String(30), nullable=False, default="ACTIVE")
    created_at: Any = Column(PortableUTC(), nullable=False)
    created_by_id: Any = Column(PortableUUID(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# wave_util_rows
# ─────────────────────────────────────────────────────────────────────────────


class WaveUtilRow(Base):
    """
    One discovered server row for a WaveUtil import.

    ``current_rev_id`` is nullable; the FK to ``wave_util_revisions`` uses
    ``use_alter=True`` to break the circular dependency so that
    ``metadata.create_all()`` can determine a valid DDL creation order.

    Table: ``wave_util_rows``
    PK auto-name:  ``pk_wave_util_rows``          (17 chars ✓)
    UQ explicit:   ``uq_wrow_app_norm``            (16 chars ✓)
    FK explicit:   ``fk_wrow_appl``               (12 chars ✓)
    FK explicit:   ``fk_wrow_intk``               (12 chars ✓)
    FK explicit:   ``fk_wrow_act``                (11 chars ✓)
    FK explicit:   ``fk_wrow_wrev`` (use_alter)   (12 chars ✓)
    """

    __tablename__ = "wave_util_rows"
    __table_args__ = (
        # Explicit name: auto-name uq_wave_util_rows_application_id = 32 chars ✗
        UniqueConstraint(
            "application_id",
            "normalized_server_name",
            name="uq_wrow_app_norm",
        ),
        # FK: wave_util_rows.application_id → applications.id
        ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_wrow_appl",
        ),
        # FK: wave_util_rows.intake_id → intakes.id  (nullable)
        ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_wrow_intk",
        ),
        # FK: wave_util_rows.created_by_id → actors.id
        ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_wrow_act",
        ),
        # FK: wave_util_rows.current_rev_id → wave_util_revisions.id
        # use_alter=True breaks the circular dependency with wave_util_revisions
        # so create_all() can determine a valid DDL order.
        ForeignKeyConstraint(
            ["current_rev_id"],
            ["wave_util_revisions.id"],
            name="fk_wrow_wrev",
            use_alter=True,
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=True)
    server_name: Any = Column(String(500), nullable=False)
    normalized_server_name: Any = Column(String(500), nullable=False)
    environment: Any = Column(String(100), nullable=True)
    scope: Any = Column(String(100), nullable=True)
    state: Any = Column(String(30), nullable=False, default="ACTIVE")
    # nullable: set after first revision inserted (cycle-breaker)
    current_rev_id: Any = Column(PortableUUID(), nullable=True)
    created_at: Any = Column(PortableUTC(), nullable=False)
    updated_at: Any = Column(PortableUTC(), nullable=False)
    row_version: Any = Column(Integer(), nullable=False, default=1)
    created_by_id: Any = Column(PortableUUID(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# wave_util_revisions
# ─────────────────────────────────────────────────────────────────────────────


class WaveUtilRevision(Base):
    """
    Append-only revision snapshot of a WaveUtilRow.

    Table: ``wave_util_revisions``
    PK auto-name:  ``pk_wave_util_revisions``        (22 chars ✓)
    UQ auto-name:  ``uq_wave_util_revisions_row_id``  (29 chars ✓)
    FK explicit:   ``fk_wrev_wrow``                  (12 chars ✓)
    FK explicit:   ``fk_wrev_act``                   (11 chars ✓)
    """

    __tablename__ = "wave_util_revisions"
    __table_args__ = (
        # UQ auto-name: uq_wave_util_revisions_row_id = 29 chars ✓ (column_0 = row_id)
        UniqueConstraint("row_id", "revision_number"),
        # FK: wave_util_revisions.row_id → wave_util_rows.id
        ForeignKeyConstraint(
            ["row_id"],
            ["wave_util_rows.id"],
            name="fk_wrev_wrow",
        ),
        # FK: wave_util_revisions.authored_by_id → actors.id
        ForeignKeyConstraint(
            ["authored_by_id"],
            ["actors.id"],
            name="fk_wrev_act",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    row_id: Any = Column(PortableUUID(), nullable=False)
    revision_number: Any = Column(Integer(), nullable=False)
    field_values_json: Any = Column(CanonicalJSON(), nullable=False)
    authored_at: Any = Column(PortableUTC(), nullable=False)
    authored_by_id: Any = Column(PortableUUID(), nullable=False)
