"""Topology generation tables.

Adds three domain tables for T02 (Topology Persistence):
  topo_base     — uploaded base diagram artifacts
  gen_runs      — immutable generation run records
  gen_artifacts — generated diagram and report artifacts

Tables (dependency order for CREATE):
  topo_base     → applications, intakes, actors
  gen_runs      → applications, intakes, int_snaps, topo_base, actors
  gen_artifacts → gen_runs

Physical column types follow the TypeDecorator impl types:
  PortableUUID  → CHAR(36)     (String(36) impl)
  PortableUTC   → VARCHAR(32)  (String(32) impl)
  Sha256Hex    → CHAR(64)     (String(64) impl)
  Text         → TEXT

All constraint names ≤ 30 characters (Oracle 12c conservative limit).
All column names ≤ 30 characters.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-14 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. topo_base — Base diagram artifacts
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "topo_base",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.CHAR(64), nullable=False),
        sa.Column("content_address", sa.String(255), nullable=False),
        sa.Column("environment", sa.String(32), nullable=True),
        sa.Column("site", sa.String(64), nullable=True),
        sa.Column("variant", sa.String(32), nullable=True),
        sa.Column("review_state", sa.String(32), nullable=False),
        sa.Column("uploaded_by_id", sa.CHAR(36), nullable=False),
        sa.Column("uploaded_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        # Primary key
        sa.PrimaryKeyConstraint("id", name="pk_topo_base"),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_tpbs_app",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_tpbs_int",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["actors.id"],
            name="fk_tpbs_act",
        ),
    )
    op.create_index("ix_tpbs_intake", "topo_base", ["intake_id"])
    op.create_index("ix_tpbs_sha", "topo_base", ["sha256_hex"])

    # ─────────────────────────────────────────────────────────────────────
    # 2. gen_runs — Generation run records
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "gen_runs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("snapshot_id", sa.CHAR(36), nullable=False),
        sa.Column("snapshot_sha256", sa.CHAR(64), nullable=False),
        sa.Column("catalog_sha256", sa.CHAR(64), nullable=False),
        sa.Column("base_artifact_id", sa.CHAR(36), nullable=False),
        sa.Column("base_sha256", sa.CHAR(64), nullable=False),
        sa.Column("config_version", sa.String(32), nullable=True),
        sa.Column("config_sha256", sa.CHAR(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("readiness_json", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(32), nullable=False),
        sa.Column("approved_by_id", sa.CHAR(36), nullable=True),
        sa.Column("approved_at", sa.String(32), nullable=True),
        sa.Column("approval_rationale", sa.Text(), nullable=True),
        sa.Column("superseded_by_id", sa.CHAR(36), nullable=True),
        sa.Column("requested_by_id", sa.CHAR(36), nullable=False),
        sa.Column("requested_at", sa.String(32), nullable=False),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        # Primary key
        sa.PrimaryKeyConstraint("id", name="pk_gen_runs"),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_gnrn_app",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_gnrn_int",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["int_snaps.id"],
            name="fk_gnrn_snp",
        ),
        sa.ForeignKeyConstraint(
            ["base_artifact_id"],
            ["topo_base.id"],
            name="fk_gnrn_bas",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["actors.id"],
            name="fk_gnrn_req",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["actors.id"],
            name="fk_gnrn_apr",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["gen_runs.id"],
            name="fk_gnrn_sup",
        ),
    )
    op.create_index("ix_gnrn_intake", "gen_runs", ["intake_id"])
    op.create_index("ix_gnrn_status", "gen_runs", ["status"])

    # ─────────────────────────────────────────────────────────────────────
    # 3. gen_artifacts — Generated artifacts
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "gen_artifacts",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("generation_run_id", sa.CHAR(36), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.CHAR(64), nullable=False),
        sa.Column("content_address", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        # Primary key
        sa.PrimaryKeyConstraint("id", name="pk_gen_artifacts"),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["gen_runs.id"],
            name="fk_gnaf_run",
        ),
    )
    op.create_index("ix_gnaf_run", "gen_artifacts", ["generation_run_id"])
    op.create_index("ix_gnaf_type", "gen_artifacts", ["artifact_type"])


def downgrade() -> None:
    op.drop_index("ix_gnaf_type", table_name="gen_artifacts")
    op.drop_index("ix_gnaf_run", table_name="gen_artifacts")
    op.drop_table("gen_artifacts")

    op.drop_index("ix_gnrn_status", table_name="gen_runs")
    op.drop_index("ix_gnrn_intake", table_name="gen_runs")
    op.drop_table("gen_runs")

    op.drop_index("ix_tpbs_sha", table_name="topo_base")
    op.drop_index("ix_tpbs_intake", table_name="topo_base")
    op.drop_table("topo_base")
