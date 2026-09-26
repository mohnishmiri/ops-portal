"""Add application interface epoch and deterministic interface access index."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    orphan_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM interfaces i "
            "LEFT JOIN applications a ON a.id = i.application_id "
            "WHERE a.id IS NULL"
        )
    ).scalar_one()
    if orphan_count:
        raise RuntimeError(
            "Cannot add interface epoch fencing: "
            f"found {orphan_count} interface row(s) without an application"
        )
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "interface_epoch",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
    op.create_index(
        "ix_irec_app_state_id",
        "interfaces",
        ["application_id", "state", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_irec_app_state_id", table_name="interfaces")
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("interface_epoch")
