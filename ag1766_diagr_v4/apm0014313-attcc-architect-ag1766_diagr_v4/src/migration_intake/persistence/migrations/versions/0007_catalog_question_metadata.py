"""Add catalog question metadata required by registry-driven editors.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("cat_questions")
    }
    with op.batch_alter_table("cat_questions") as batch_op:
        if "help_text" not in existing_columns:
            batch_op.add_column(sa.Column("help_text", sa.Text(), nullable=True))
        if "units" not in existing_columns:
            batch_op.add_column(sa.Column("units", sa.String(32), nullable=True))
        if "field_name" not in existing_columns:
            batch_op.add_column(sa.Column("field_name", sa.String(64), nullable=True))
        if "response_schema_version" not in existing_columns:
            batch_op.add_column(
                sa.Column("response_schema_version", sa.String(32), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("cat_questions") as batch_op:
        batch_op.drop_column("response_schema_version")
        batch_op.drop_column("field_name")
        batch_op.drop_column("units")
        batch_op.drop_column("help_text")
