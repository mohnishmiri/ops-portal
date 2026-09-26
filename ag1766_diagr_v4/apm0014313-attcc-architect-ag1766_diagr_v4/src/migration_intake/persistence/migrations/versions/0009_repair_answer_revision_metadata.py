"""Repair answer revision metadata missing from historically stamped databases.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("ans_revisions")
    }
    with op.batch_alter_table("ans_revisions") as batch_op:
        if "change_reason" not in existing_columns:
            batch_op.add_column(sa.Column("change_reason", sa.Text(), nullable=True))
        if "response_schema_version" not in existing_columns:
            batch_op.add_column(sa.Column("response_schema_version", sa.String(32), nullable=True))
        if "raw_boundary_value" not in existing_columns:
            batch_op.add_column(sa.Column("raw_boundary_value", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ans_revisions") as batch_op:
        batch_op.drop_column("raw_boundary_value")
        batch_op.drop_column("response_schema_version")
        batch_op.drop_column("change_reason")
