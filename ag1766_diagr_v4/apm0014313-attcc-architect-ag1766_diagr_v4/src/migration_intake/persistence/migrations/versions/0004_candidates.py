"""Candidates and answer evidence links.

Creates tables for candidate values from imports/AI and their links
to answer revisions.

Tables:
  candidates → import_runs, applications, intakes, evidence_items, actors
  candidate_findings → candidates, import_runs
  answer_evidence_links → ans_revisions, evidence_items, candidates

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. candidates
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "candidates",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("import_run_id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("evidence_item_id", sa.CHAR(36), nullable=False),
        sa.Column("target_kind", sa.String(32), nullable=False),
        sa.Column("target_key", sa.String(128), nullable=False),
        sa.Column("origin", sa.String(64), nullable=False),
        sa.Column("extractor_version", sa.String(32), nullable=False),
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("response_schema_version", sa.String(32), nullable=True),
        sa.Column("source_locator", sa.Text(), nullable=True),
        sa.Column("raw_value_json", sa.Text(), nullable=False),
        sa.Column("normalized_value_json", sa.Text(), nullable=True),
        sa.Column("scope_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reconciliation_outcome", sa.String(32), nullable=True),
        sa.Column("validation_json", sa.Text(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("decided_by_id", sa.CHAR(36), nullable=True),
        sa.Column("decided_at", sa.String(32), nullable=True),
        sa.Column("decision_rationale", sa.Text(), nullable=True),
        sa.Column("accepted_value_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["import_runs.id"],
            name="fk_cand_run",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_cand_app",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_cand_intake",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name="fk_cand_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["actors.id"],
            name="fk_cand_decided_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidates"),
    )
    op.create_index("ix_cand_intake_state", "candidates", ["intake_id", "state"])
    op.create_index("ix_cand_run", "candidates", ["import_run_id"])
    op.create_index("ix_cand_target", "candidates", ["intake_id", "target_kind", "target_key"])
    op.create_index("ix_cand_evidence", "candidates", ["evidence_item_id"])

    # ─────────────────────────────────────────────────────────────────────
    # 2. candidate_findings
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "candidate_findings",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("candidate_id", sa.CHAR(36), nullable=True),
        sa.Column("import_run_id", sa.CHAR(36), nullable=False),
        sa.Column("finding_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("source_locator", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name="fk_cfind_cand",
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["import_runs.id"],
            name="fk_cfind_run",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_findings"),
    )
    op.create_index("ix_cfind_cand", "candidate_findings", ["candidate_id"])
    op.create_index("ix_cfind_run", "candidate_findings", ["import_run_id"])

    # ─────────────────────────────────────────────────────────────────────
    # 3. answer_evidence_links
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "answer_evidence_links",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("revision_id", sa.CHAR(36), nullable=False),
        sa.Column("evidence_item_id", sa.CHAR(36), nullable=False),
        sa.Column("candidate_id", sa.CHAR(36), nullable=True),
        sa.Column("link_type", sa.String(32), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["ans_revisions.id"],
            name="fk_ael_rev",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name="fk_ael_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name="fk_ael_cand",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_answer_evidence_links"),
        sa.UniqueConstraint("revision_id", "evidence_item_id", name="uq_ael_rev_evid"),
    )
    op.create_index("ix_ael_rev", "answer_evidence_links", ["revision_id"])
    op.create_index("ix_ael_evidence", "answer_evidence_links", ["evidence_item_id"])


def downgrade() -> None:
    op.drop_table("answer_evidence_links")
    op.drop_table("candidate_findings")
    op.drop_table("candidates")
