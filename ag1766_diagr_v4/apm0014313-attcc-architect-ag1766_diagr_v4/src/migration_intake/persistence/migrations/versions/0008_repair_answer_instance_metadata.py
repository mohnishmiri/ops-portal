"""Repair answer metadata missing from databases stamped at earlier revisions.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("ans_instances")
    }
    with op.batch_alter_table("ans_instances") as batch_op:
        if "applicability" not in existing_columns:
            batch_op.add_column(
                sa.Column("applicability", sa.String(32), nullable=False, server_default="APPLICABLE")
            )
        if "value_state" not in existing_columns:
            batch_op.add_column(
                sa.Column("value_state", sa.String(32), nullable=False, server_default="EMPTY")
            )
        if "review_state" not in existing_columns:
            batch_op.add_column(
                sa.Column("review_state", sa.String(32), nullable=False, server_default="UNREVIEWED")
            )
        if "updated_at" not in existing_columns:
            batch_op.add_column(sa.Column("updated_at", sa.String(32), nullable=True))
        if "row_version" not in existing_columns:
            batch_op.add_column(sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))

    op.execute("UPDATE ans_instances SET updated_at = created_at WHERE updated_at IS NULL")
    with op.batch_alter_table("ans_instances") as batch_op:
        batch_op.alter_column("updated_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("ans_instances") as batch_op:
        batch_op.drop_column("row_version")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("review_state")
        batch_op.drop_column("value_state")
        batch_op.drop_column("applicability")
