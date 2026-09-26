"""Add append-only ai_mapping_runs lineage table."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_mapping_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("evidence_item_id", sa.CHAR(36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=32), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("fragment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("response_hash", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_detail_redacted", sa.String(length=255), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.String(length=32), nullable=False),
        sa.Column("finished_at", sa.String(length=32), nullable=True),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], name="fk_airun_app"),
        sa.ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_airun_int"),
        sa.ForeignKeyConstraint(["evidence_item_id"], ["evidence_items.id"], name="fk_airun_evi"),
        sa.ForeignKeyConstraint(["created_by_id"], ["actors.id"], name="fk_airun_act"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_mapping_runs")),
    )
    op.create_index("ix_airun_app", "ai_mapping_runs", ["application_id"], unique=False)
    op.create_index("ix_airun_int", "ai_mapping_runs", ["intake_id"], unique=False)
    op.create_index("ix_airun_evi", "ai_mapping_runs", ["evidence_item_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_airun_evi", table_name="ai_mapping_runs")
    op.drop_index("ix_airun_int", table_name="ai_mapping_runs")
    op.drop_index("ix_airun_app", table_name="ai_mapping_runs")
    op.drop_table("ai_mapping_runs")
