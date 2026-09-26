"""Add scoped resource and typed relationship persistence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "res_resources",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("logical_key", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("environment", sa.String(16), nullable=True),
        sa.Column("site", sa.String(64), nullable=True),
        sa.Column("tier", sa.String(32), nullable=True),
        sa.Column("parent_id", sa.CHAR(36), nullable=True),
        sa.Column("current_revision_id", sa.CHAR(36), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resource_state", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("successor_id", sa.CHAR(36), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_res_intake"),
        sa.ForeignKeyConstraint(["parent_id"], ["res_resources.id"], name="fk_res_parent"),
        sa.ForeignKeyConstraint(["successor_id"], ["res_resources.id"], name="fk_res_successor"),
        sa.PrimaryKeyConstraint("id", name="pk_res_resources"),
        sa.UniqueConstraint("intake_id", "logical_key", "lifecycle", "scope_key", name="uq_res_scope"),
    )
    op.create_index("ix_res_intake", "res_resources", ["intake_id"])
    op.create_index("ix_res_kind", "res_resources", ["intake_id", "kind"])
    op.create_index("ix_res_scope", "res_resources", ["intake_id", "scope_key"])
    op.create_index("ix_res_parent", "res_resources", ["parent_id"])

    op.create_table(
        "res_revisions",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("resource_id", sa.CHAR(36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("review_state", sa.String(16), nullable=False),
        sa.Column("provenance_references", sa.Text(), nullable=True),
        sa.Column("authored_at", sa.String(32), nullable=False),
        sa.Column("authored_by", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["res_resources.id"], name="fk_rev_resource"),
        sa.PrimaryKeyConstraint("id", name="pk_res_revisions"),
        sa.UniqueConstraint("resource_id", "revision_number", name="uq_res_rev_num"),
    )
    op.create_index("ix_rev_resource", "res_revisions", ["resource_id"])

    op.create_table(
        "res_links",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("relationship_type", sa.String(64), nullable=False),
        sa.Column("source_resource_id", sa.CHAR(36), nullable=False),
        sa.Column("target_resource_id", sa.CHAR(36), nullable=False),
        sa.Column("current_revision_id", sa.CHAR(36), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("link_state", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_rlink_intake"),
        sa.ForeignKeyConstraint(["source_resource_id"], ["res_resources.id"], name="fk_rlink_source"),
        sa.ForeignKeyConstraint(["target_resource_id"], ["res_resources.id"], name="fk_rlink_target"),
        sa.PrimaryKeyConstraint("id", name="pk_res_links"),
        sa.UniqueConstraint("intake_id", "relationship_type", "source_resource_id", "target_resource_id", name="uq_rlink_identity"),
    )
    op.create_index("ix_rlink_intake", "res_links", ["intake_id"])
    op.create_index("ix_rlink_source", "res_links", ["source_resource_id"])
    op.create_index("ix_rlink_target", "res_links", ["target_resource_id"])

    op.create_table(
        "res_link_revisions",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("link_id", sa.CHAR(36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("review_state", sa.String(16), nullable=False),
        sa.Column("provenance_references", sa.Text(), nullable=True),
        sa.Column("authored_at", sa.String(32), nullable=False),
        sa.Column("authored_by", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["res_links.id"], name="fk_rlrev_link"),
        sa.PrimaryKeyConstraint("id", name="pk_res_link_revisions"),
        sa.UniqueConstraint("link_id", "revision_number", name="uq_rlrev_num"),
    )
    op.create_index("ix_rlrev_link", "res_link_revisions", ["link_id"])


def downgrade() -> None:
    op.drop_index("ix_rlrev_link", table_name="res_link_revisions")
    op.drop_table("res_link_revisions")
    op.drop_index("ix_rlink_target", table_name="res_links")
    op.drop_index("ix_rlink_source", table_name="res_links")
    op.drop_index("ix_rlink_intake", table_name="res_links")
    op.drop_table("res_links")
    op.drop_index("ix_rev_resource", table_name="res_revisions")
    op.drop_table("res_revisions")
    op.drop_index("ix_res_parent", table_name="res_resources")
    op.drop_index("ix_res_scope", table_name="res_resources")
    op.drop_index("ix_res_kind", table_name="res_resources")
    op.drop_index("ix_res_intake", table_name="res_resources")
    op.drop_table("res_resources")
