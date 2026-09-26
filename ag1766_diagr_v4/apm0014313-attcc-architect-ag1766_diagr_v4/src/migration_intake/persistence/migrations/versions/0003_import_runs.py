"""Import runs, sheet results, and findings.

Adds three domain tables for P05b (Import Runs, Sheet Results, Findings Persistence):
  import_runs          — one row per import execution attempt
  import_sheet_results — one row per worksheet processed in a run
  import_findings      — structured finding records emitted during a run

Tables (dependency order for CREATE):
  import_runs           — FKs → applications, intakes, evidence_items, actors
  import_sheet_results  — FK → import_runs
  import_findings       — FK → import_runs

Physical column types follow the TypeDecorator impl types (same as 0001 and 0002):
  PortableUUID  → CHAR(36)     (String(36) impl)
  PortableUTC   → VARCHAR(32)  (String(32) impl)
  CanonicalJSON → TEXT         (Text impl)
  Integer       → INTEGER

All constraint names ≤ 30 characters (Oracle 12c conservative limit).
All column names ≤ 30 characters.

Revision ID: 0003
Revises: 0002
Create Date: 2025-06-01 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. import_runs   FKs → applications, intakes, evidence_items, actors
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "import_runs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=True),
        sa.Column("evidence_item_id", sa.CHAR(36), nullable=True),
        sa.Column("contract_name", sa.String(100), nullable=False),
        sa.Column("parser_version", sa.String(50), nullable=False),
        sa.Column(
            "state",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("total_sheets", sa.Integer(), nullable=True),
        sa.Column(
            "total_candidates",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_findings",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.String(32), nullable=True),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        # FK: import_runs.application_id → applications.id
        # auto-name: fk_import_runs_application_id_applications = 42 chars ✗
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_irun_appl",
        ),
        # FK: import_runs.intake_id → intakes.id
        # auto-name: fk_import_runs_intake_id_intakes = 32 chars ✗
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_irun_intk",
        ),
        # FK: import_runs.evidence_item_id → evidence_items.id
        # auto-name: fk_import_runs_evidence_item_id_evidence_items = 46 chars ✗
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name="fk_irun_evid",
        ),
        # FK: import_runs.created_by_id → actors.id
        # auto-name: fk_import_runs_created_by_id_actors = 35 chars ✗
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_irun_act",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_runs"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 2. import_sheet_results   FK → import_runs
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "import_sheet_results",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("run_id", sa.CHAR(36), nullable=False),
        sa.Column("sheet_name", sa.String(200), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column(
            "candidate_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "finding_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "blank_rows_skipped",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.String(1000), nullable=True),
        # FK: import_sheet_results.run_id → import_runs.id
        # auto-name: fk_import_sheet_results_run_id_import_runs = 42 chars ✗
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["import_runs.id"],
            name="fk_isht_irun",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_sheet_results"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 3. import_findings   FK → import_runs
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "import_findings",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("run_id", sa.CHAR(36), nullable=False),
        sa.Column("sheet_name", sa.String(200), nullable=False),
        sa.Column("finding_type", sa.String(100), nullable=False),
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'WARNING'"),
        ),
        sa.Column("source_locator", sa.String(500), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        # FK: import_findings.run_id → import_runs.id
        # auto-name: fk_import_findings_run_id_import_runs = 37 chars ✗
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["import_runs.id"],
            name="fk_ifnd_irun",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_findings"),
    )


def downgrade() -> None:
    # Drop in reverse dependency order.
    # import_findings and import_sheet_results reference import_runs,
    # so they must be dropped first.

    # 1. Drop import_findings (FK → import_runs)
    op.drop_table("import_findings")

    # 2. Drop import_sheet_results (FK → import_runs)
    op.drop_table("import_sheet_results")

    # 3. Drop import_runs (FKs → applications, intakes, evidence_items, actors)
    op.drop_table("import_runs")
