"""Add topology template release registry table."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tpl_releases",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("content_address", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("tab_count", sa.Integer(), nullable=False),
        sa.Column("variant_manifest", sa.Text(), nullable=False),
        sa.Column("compiler_version", sa.String(length=32), nullable=False),
        sa.Column("compiler_report", sa.Text(), nullable=True),
        sa.Column("pub_state", sa.String(length=32), nullable=False),
        sa.Column("published_at", sa.String(length=32), nullable=True),
        sa.Column("published_by_id", sa.CHAR(length=36), nullable=True),
        sa.Column("retired_at", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["published_by_id"], ["actors.id"], name="fk_trel_actor"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tpl_releases")),
        sa.UniqueConstraint("source_sha256", name="uq_trel_sha"),
    )
    op.add_column(
        "topo_base",
        sa.Column("template_release_id", sa.CHAR(length=36), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("topo_base") as batch_op:
        batch_op.drop_column("template_release_id")
    op.drop_table("tpl_releases")
