"""Persist source identity decisions on import runs."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migration_intake.persistence.types import CanonicalJSON

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("import_runs")
    }
    with op.batch_alter_table("import_runs") as batch_op:
        if "identity_decision" not in existing_columns:
            batch_op.add_column(sa.Column("identity_decision", sa.String(40), nullable=True))
        if "source_identity_raw" not in existing_columns:
            batch_op.add_column(sa.Column("source_identity_raw", sa.String(500), nullable=True))
        if "source_identity_normalized" not in existing_columns:
            batch_op.add_column(sa.Column("source_identity_normalized", sa.String(500), nullable=True))
        if "identity_detail" not in existing_columns:
            batch_op.add_column(sa.Column("identity_detail", CanonicalJSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("import_runs") as batch_op:
        batch_op.drop_column("identity_detail")
        batch_op.drop_column("source_identity_normalized")
        batch_op.drop_column("source_identity_raw")
        batch_op.drop_column("identity_decision")
