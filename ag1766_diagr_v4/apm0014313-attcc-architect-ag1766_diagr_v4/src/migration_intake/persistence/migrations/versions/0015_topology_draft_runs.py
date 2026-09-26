"""Allow topology generation before an intake is frozen."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("gen_runs") as batch_op:
        batch_op.alter_column("snapshot_id", nullable=True)
        batch_op.alter_column("snapshot_sha256", nullable=True)
        batch_op.alter_column("catalog_sha256", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("gen_runs") as batch_op:
        batch_op.alter_column("catalog_sha256", nullable=False)
        batch_op.alter_column("snapshot_sha256", nullable=False)
        batch_op.alter_column("snapshot_id", nullable=False)
