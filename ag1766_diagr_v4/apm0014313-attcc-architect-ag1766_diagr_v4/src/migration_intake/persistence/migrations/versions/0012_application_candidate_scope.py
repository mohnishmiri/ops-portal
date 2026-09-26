"""Backfill application scope for questionnaire import candidates."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE candidates "
            "SET scope_json = '{\"scope\":\"APPLICATION\"}' "
            "WHERE target_kind = 'QUESTION' AND scope_json IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE candidates "
            "SET scope_json = NULL "
            "WHERE target_kind = 'QUESTION' "
            "AND scope_json = '{\"scope\":\"APPLICATION\"}'"
        )
    )
