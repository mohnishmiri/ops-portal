"""Add capture epochs and immutable compatibility pins."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_attempts = connection.execute(
        sa.text(
            "SELECT intake_id, semantic_input_hash, attempt_number, COUNT(*) AS duplicate_count "
            "FROM gen_runs WHERE semantic_input_hash IS NOT NULL "
            "GROUP BY intake_id, semantic_input_hash, attempt_number HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if duplicate_attempts:
        raise RuntimeError(
            "Cannot add governed run-attempt uniqueness: "
            f"found {len(duplicate_attempts)} duplicate identity group(s)"
        )
    with op.batch_alter_table("intakes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "content_epoch",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
    with op.batch_alter_table("topo_inputs") as batch_op:
        batch_op.add_column(sa.Column("compatibility_id", sa.CHAR(36), nullable=True))
        batch_op.add_column(sa.Column("compatibility_key", sa.CHAR(64), nullable=True))
        batch_op.add_column(sa.Column("compatibility_result_hash", sa.CHAR(64), nullable=True))
        batch_op.create_foreign_key("fk_tinp_cmp", "topo_compat", ["compatibility_id"], ["id"])
    if op.get_bind().dialect.name == "oracle":
        op.add_column("gen_runs", sa.Column("rerun_reason", sa.Text(), nullable=True))
        op.create_unique_constraint(
            "uq_grun_attempt",
            "gen_runs",
            ["intake_id", "semantic_input_hash", "attempt_number"],
        )
    else:
        with op.batch_alter_table("gen_runs", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("rerun_reason", sa.Text(), nullable=True))
            batch_op.create_unique_constraint(
                "uq_grun_attempt",
                ["intake_id", "semantic_input_hash", "attempt_number"],
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "oracle":
        op.drop_constraint("uq_grun_attempt", "gen_runs", type_="unique")
        op.drop_column("gen_runs", "rerun_reason")
    else:
        with op.batch_alter_table("gen_runs", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_grun_attempt", type_="unique")
            batch_op.drop_column("rerun_reason")
    with op.batch_alter_table("topo_inputs") as batch_op:
        batch_op.drop_constraint("fk_tinp_cmp", type_="foreignkey")
        batch_op.drop_column("compatibility_result_hash")
        batch_op.drop_column("compatibility_key")
        batch_op.drop_column("compatibility_id")
    with op.batch_alter_table("intakes") as batch_op:
        batch_op.drop_column("content_epoch")
