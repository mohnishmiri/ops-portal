"""Intake snapshots for frozen intakes.

Adds one domain table for P07 (Snapshot Persistence):
  int_snaps — immutable snapshot of a frozen intake

Tables (dependency order for CREATE):
  int_snaps — FKs → intakes, cat_rels, actors

Physical column types follow the TypeDecorator impl types:
  PortableUUID  → CHAR(36)     (String(36) impl)
  PortableUTC   → VARCHAR(32)  (String(32) impl)
  Sha256Hex    → CHAR(64)     (String(64) impl)
  Text         → TEXT

All constraint names ≤ 30 characters (Oracle 12c conservative limit).
All column names ≤ 30 characters.

Revision ID: 0006
Revises: 0003
Create Date: 2025-06-01 00:00:00.000000

Note: Migrations 0004 and 0005 are reserved for candidates and answer_evidence_links
tables which are currently created via metadata.create_all() in tests.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. int_snaps   FKs → intakes, cat_rels, actors
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "int_snaps",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("catalog_id", sa.CHAR(36), nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("catalog_sha256", sa.CHAR(64), nullable=False),
        sa.Column("canonical_json", sa.Text(), nullable=False),
        sa.Column("sha256_hex", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        # Primary key
        sa.PrimaryKeyConstraint("id", name="pk_int_snaps"),
        # Unique constraint: each intake can have at most one snapshot
        sa.UniqueConstraint("intake_id", name="uq_snap_intake"),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_snap_int",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_id"],
            ["cat_releases.id"],
            name="fk_snap_cat",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_snap_act",
        ),
    )

    # Index for lookup by hash
    op.create_index("ix_snap_hash", "int_snaps", ["sha256_hex"])


def downgrade() -> None:
    op.drop_index("ix_snap_hash", table_name="int_snaps")
    op.drop_table("int_snaps")
