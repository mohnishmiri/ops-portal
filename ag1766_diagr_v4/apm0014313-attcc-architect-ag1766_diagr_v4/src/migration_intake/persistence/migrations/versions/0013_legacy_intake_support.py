"""Add legacy intake workbook import support.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-11

Changes:
- Add import_lane to import_runs (SOURCE_DOCUMENT, GAP_WORKBOOK, LEGACY_INTAKE)
- Add matched_identifier_type to import_runs (CORRELATION, MOTS, ITAP)
- Add base_answer_revision to candidates (for stale-answer detection)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add legacy intake support fields."""
    # Check existing columns to support idempotent migrations
    existing_import_runs_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("import_runs")
    }
    existing_candidates_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("candidates")
    }

    # ── import_runs changes ──────────────────────────────────────────────
    with op.batch_alter_table("import_runs") as batch_op:
        # Add import_lane to distinguish upload lanes
        if "import_lane" not in existing_import_runs_columns:
            batch_op.add_column(
                sa.Column(
                    "import_lane",
                    sa.String(30),
                    nullable=True,  # Nullable for existing rows
                )
            )

        # Add matched_identifier_type to record which ID type was used
        if "matched_identifier_type" not in existing_import_runs_columns:
            batch_op.add_column(
                sa.Column(
                    "matched_identifier_type",
                    sa.String(20),
                    nullable=True,  # CORRELATION, MOTS, ITAP, or NULL
                )
            )

    # Backfill existing rows with default lane
    # Existing imports are SOURCE_DOCUMENT lane (UAQ, Interface Tracking, WaveUtil)
    op.execute(
        """
        UPDATE import_runs
        SET import_lane = 'SOURCE_DOCUMENT'
        WHERE import_lane IS NULL
        """
    )

    # ── candidates changes ────────────────────────────────────────────────
    with op.batch_alter_table("candidates") as batch_op:
        # Add base_answer_revision for stale-answer detection
        if "base_answer_revision" not in existing_candidates_columns:
            batch_op.add_column(
                sa.Column(
                    "base_answer_revision",
                    sa.Integer(),
                    nullable=True,  # NULL for non-answer candidates (registers, etc.)
                )
            )


def downgrade() -> None:
    """Remove legacy intake support fields."""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_column("base_answer_revision")

    with op.batch_alter_table("import_runs") as batch_op:
        batch_op.drop_column("matched_identifier_type")
        batch_op.drop_column("import_lane")
