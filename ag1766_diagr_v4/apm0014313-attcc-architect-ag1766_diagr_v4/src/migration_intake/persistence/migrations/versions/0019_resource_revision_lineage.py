"""Persist parent and lifecycle state on every resource revision."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("res_revisions") as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.CHAR(36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "resource_state",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'ACTIVE'"),
            )
        )
        batch_op.add_column(sa.Column("change_reason", sa.String(255), nullable=True))
        batch_op.create_foreign_key(
            "fk_rev_parent", "res_resources", ["parent_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("res_revisions") as batch_op:
        batch_op.drop_constraint("fk_rev_parent", type_="foreignkey")
        batch_op.drop_column("change_reason")
        batch_op.drop_column("resource_state")
        batch_op.drop_column("parent_id")
