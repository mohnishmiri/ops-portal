"""Scope evidence deduplication to application and intake."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical databases may contain evidence rows created before the ORM
    # enforced these audit fields as non-null. Normalize them before the
    # constraint change so SQLite table rebuilds and Oracle ALTER TABLE both
    # receive valid values.
    op.execute(
        sa.text(
            "UPDATE evidence_items "
            "SET created_at = '1970-01-01T00:00:00+00:00' "
            "WHERE created_at IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE evidence_items "
            "SET created_by_id = (SELECT MIN(id) FROM actors) "
            "WHERE created_by_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM evidence_items "
            "WHERE id NOT IN ("
            "SELECT MIN(id) FROM evidence_items "
            "GROUP BY application_id, intake_id, storage_key"
            ")"
        )
    )
    with op.batch_alter_table("evidence_items") as batch_op:
        batch_op.drop_constraint("uq_evidence_items_storage_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_evid_app_intake_storage",
            ["application_id", "intake_id", "storage_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_items") as batch_op:
        batch_op.drop_constraint("uq_evid_app_intake_storage", type_="unique")
        batch_op.create_unique_constraint(
            "uq_evidence_items_storage_key",
            ["storage_key"],
        )
