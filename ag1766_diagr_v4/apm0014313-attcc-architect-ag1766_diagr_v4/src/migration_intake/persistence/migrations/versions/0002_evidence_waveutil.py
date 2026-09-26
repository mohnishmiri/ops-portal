"""Evidence items, WaveUtil rows, and WaveUtil revisions.

Adds three domain tables for P05 (Evidence and WaveUtil Persistence):
  evidence_items       — uploaded evidence files (one per S3/storage object)
  wave_util_rows       — one row per discovered server per application
  wave_util_revisions  — append-only revision snapshots of a wave_util_rows row

Tables (dependency order for CREATE):
  evidence_items        — FKs → applications, intakes, actors
  wave_util_rows        — FKs → applications, intakes, actors
                          (circular FK to wave_util_revisions deferred via batch alter)
  wave_util_revisions   — FKs → wave_util_rows, actors
  ADD CONSTRAINT fk_wrow_wrev  (wave_util_rows → wave_util_revisions)

Physical column types follow the TypeDecorator impl types (same as 0001):
  PortableUUID  → CHAR(36)     (String(36) impl)
  PortableUTC   → VARCHAR(32)  (String(32) impl)
  Sha256Hex     → VARCHAR(64)  (String(64) impl)
  CanonicalJSON → TEXT         (Text impl)
  BigInteger    → BIGINT

All constraint names ≤ 30 characters (Oracle 12c conservative limit).

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. evidence_items   FKs → applications, intakes, actors
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=True),
        sa.Column("storage_key", sa.String(100), nullable=False),
        sa.Column("sha256_hex", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "media_type",
            sa.String(80),
            nullable=False,
            server_default=sa.text("'application/octet-stream'"),
        ),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column(
            "state",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_evid_appl",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_evid_intk",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_evid_act",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_items"),
        # auto-name: uq_evidence_items_storage_key = 29 chars ✓
        sa.UniqueConstraint("storage_key", name="uq_evidence_items_storage_key"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 2. wave_util_rows   FKs → applications, intakes, actors
    #    NOTE: the circular FK to wave_util_revisions (fk_wrow_wrev) is added
    #    AFTER wave_util_revisions is created (step 4 below) using
    #    batch_alter_table to satisfy SQLite's DDL limitations.
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "wave_util_rows",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=True),
        sa.Column("server_name", sa.String(500), nullable=False),
        sa.Column("normalized_server_name", sa.String(500), nullable=False),
        sa.Column("environment", sa.String(100), nullable=True),
        sa.Column("scope", sa.String(100), nullable=True),
        sa.Column(
            "state",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        # Nullable: resolved after first revision is inserted (cycle-breaker).
        sa.Column("current_rev_id", sa.CHAR(36), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_wrow_appl",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_wrow_intk",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_wrow_act",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wave_util_rows"),
        # Explicit name: auto-name uq_wave_util_rows_application_id = 32 chars ✗
        sa.UniqueConstraint(
            "application_id",
            "normalized_server_name",
            name="uq_wrow_app_norm",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 3. wave_util_revisions   FKs → wave_util_rows, actors
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "wave_util_revisions",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("row_id", sa.CHAR(36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("field_values_json", sa.Text(), nullable=False),
        sa.Column("authored_at", sa.String(32), nullable=False),
        sa.Column("authored_by_id", sa.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["row_id"],
            ["wave_util_rows.id"],
            name="fk_wrev_wrow",
        ),
        sa.ForeignKeyConstraint(
            ["authored_by_id"],
            ["actors.id"],
            name="fk_wrev_act",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wave_util_revisions"),
        # auto-name: uq_wave_util_revisions_row_id = 29 chars ✓ (column_0 = row_id)
        sa.UniqueConstraint(
            "row_id",
            "revision_number",
            name="uq_wave_util_revisions_row_id",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 4. Close the cycle: add fk_wrow_wrev (wave_util_rows → wave_util_revisions)
    #    Use batch_alter_table because SQLite does not support
    #    ALTER TABLE ... ADD CONSTRAINT.
    # ─────────────────────────────────────────────────────────────────────
    with op.batch_alter_table("wave_util_rows", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_wrow_wrev",
            "wave_util_revisions",
            ["current_rev_id"],
            ["id"],
        )


def downgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # Drop in reverse dependency order.
    # Break the circular FK first so wave_util_rows can be dropped before
    # wave_util_revisions without violating referential integrity.
    # ─────────────────────────────────────────────────────────────────────

    # 1. Break the circular FK before dropping either wave_util table
    with op.batch_alter_table("wave_util_rows", schema=None) as batch_op:
        batch_op.drop_constraint("fk_wrow_wrev", type_="foreignkey")

    # 2. Drop wave_util_revisions (FK → wave_util_rows, actors)
    op.drop_table("wave_util_revisions")

    # 3. Drop wave_util_rows (FK → applications, intakes, actors)
    op.drop_table("wave_util_rows")

    # 4. Drop evidence_items (FK → applications, intakes, actors)
    op.drop_table("evidence_items")
