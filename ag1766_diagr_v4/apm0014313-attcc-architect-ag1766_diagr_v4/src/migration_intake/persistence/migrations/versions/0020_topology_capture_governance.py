"""Add governed topology capture, input, reservation, and review persistence.

Legacy topology rows are retained and explicitly marked ``LEGACY_UNPINNED``.
New authoritative records use immutable input pins and durable CAS fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence


revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _oracle_columns(table_name: str) -> set[str]:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT column_name FROM user_tab_columns "
            "WHERE table_name = :table_name"
        ),
        {"table_name": table_name.upper()},
    )
    return {row[0].upper() for row in rows}


def _oracle_add_columns(table_name: str, columns: tuple[sa.Column, ...]) -> None:
    existing = _oracle_columns(table_name)
    for column in columns:
        if column.name.upper() not in existing:
            op.add_column(table_name, column)


def upgrade() -> None:
    topo_base_columns = (
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("authority", sa.String(32), nullable=False, server_default="LEGACY_UNPINNED"),
        sa.Column("lifecycle", sa.String(32), nullable=False, server_default="HISTORICAL"),
        sa.Column("profile_id", sa.String(128), nullable=True),
        sa.Column("profile_version", sa.String(32), nullable=True),
        sa.Column("profile_hash", sa.CHAR(64), nullable=True),
        sa.Column("capability", sa.String(32), nullable=True),
        sa.Column("selection_json", sa.Text(), nullable=True),
        sa.Column("selection_hash", sa.CHAR(64), nullable=True),
        sa.Column("compatibility_id", sa.CHAR(36), nullable=True),
        sa.Column("reviewed_by_id", sa.CHAR(36), nullable=True),
        sa.Column("reviewed_at", sa.String(32), nullable=True),
        sa.Column("review_rationale", sa.Text(), nullable=True),
    )
    if op.get_bind().dialect.name == "oracle":
        _oracle_add_columns("topo_base", topo_base_columns)
    else:
        with op.batch_alter_table("topo_base") as batch_op:
            for column in topo_base_columns:
                batch_op.add_column(column)

    gen_run_columns = (
        sa.Column("input_id", sa.CHAR(36), nullable=True),
        sa.Column("mode", sa.String(32), nullable=True),
        sa.Column("capability", sa.String(32), nullable=True),
        sa.Column("authority", sa.String(32), nullable=False, server_default="LEGACY_UNPINNED"),
        sa.Column("phase", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("semantic_input_hash", sa.CHAR(64), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.String(32), nullable=True),
        sa.Column("manifest_hash", sa.CHAR(64), nullable=True),
    )
    if op.get_bind().dialect.name == "oracle":
        _oracle_add_columns("gen_runs", gen_run_columns)
        indexes = {
            row[0].upper()
            for row in op.get_bind().execute(
                sa.text("SELECT index_name FROM user_indexes WHERE table_name = 'GEN_RUNS'")
            )
        }
        if "IX_GNRN_INPUT" not in indexes:
            op.create_index("ix_gnrn_input", "gen_runs", ["input_id"])
    else:
        with op.batch_alter_table("gen_runs") as batch_op:
            for column in gen_run_columns:
                batch_op.add_column(column)
        op.create_index("ix_gnrn_input", "gen_runs", ["input_id"])

    if op.get_bind().dialect.name == "oracle":
        op.create_unique_constraint(
            "uq_gart_type", "gen_artifacts", ["generation_run_id", "artifact_type"]
        )
    else:
        with op.batch_alter_table("gen_artifacts", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_gart_type", ["generation_run_id", "artifact_type"]
            )

    op.create_table(
        "topo_compat",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("base_artifact_id", sa.CHAR(36), nullable=False),
        sa.Column("base_sha256", sa.CHAR(64), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("profile_version", sa.String(32), nullable=False),
        sa.Column("profile_hash", sa.CHAR(64), nullable=False),
        sa.Column("selection_json", sa.Text(), nullable=False),
        sa.Column("selection_hash", sa.CHAR(64), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("parser_policy_hash", sa.CHAR(64), nullable=False),
        sa.Column("compatibility_key", sa.CHAR(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("result_hash", sa.CHAR(64), nullable=False),
        sa.Column("checked_by_id", sa.CHAR(36), nullable=False),
        sa.Column("checked_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["base_artifact_id"], ["topo_base.id"], name="fk_tcmp_base"),
        sa.ForeignKeyConstraint(["checked_by_id"], ["actors.id"], name="fk_tcmp_actor"),
        sa.PrimaryKeyConstraint("id", name="pk_topo_compat"),
        sa.UniqueConstraint("compatibility_key", name="uq_tcmp_key"),
    )
    op.create_index("ix_tcmp_base", "topo_compat", ["base_artifact_id"])

    op.create_table(
        "topo_captures",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("content_epoch", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("canonical_json", sa.Text(), nullable=False),
        sa.Column("sha256_hex", sa.CHAR(64), nullable=False),
        sa.Column("captured_by_id", sa.CHAR(36), nullable=False),
        sa.Column("captured_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_tcap_intake"),
        sa.ForeignKeyConstraint(["captured_by_id"], ["actors.id"], name="fk_tcap_actor"),
        sa.PrimaryKeyConstraint("id", name="pk_topo_captures"),
    )
    op.create_index("ix_tcap_intake", "topo_captures", ["intake_id"])

    op.create_table(
        "topo_inputs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("snapshot_id", sa.CHAR(36), nullable=True),
        sa.Column("capture_id", sa.CHAR(36), nullable=True),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.Column("projection_sha256", sa.CHAR(64), nullable=False),
        sa.Column("selection_json", sa.Text(), nullable=False),
        sa.Column("selection_sha256", sa.CHAR(64), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("base_artifact_id", sa.CHAR(36), nullable=False),
        sa.Column("base_sha256", sa.CHAR(64), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("profile_hash", sa.CHAR(64), nullable=False),
        sa.Column("catalog_sha256", sa.CHAR(64), nullable=False),
        sa.Column("generator_version", sa.String(64), nullable=False),
        sa.Column("parser_policy_hash", sa.CHAR(64), nullable=False),
        sa.Column("layout_policy_hash", sa.CHAR(64), nullable=False),
        sa.Column("result_policy_hash", sa.CHAR(64), nullable=False),
        sa.Column("semantic_input_hash", sa.CHAR(64), nullable=False),
        sa.Column("captured_by_id", sa.CHAR(36), nullable=False),
        sa.Column("captured_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], name="fk_tinp_app"),
        sa.ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_tinp_intake"),
        sa.ForeignKeyConstraint(["base_artifact_id"], ["topo_base.id"], name="fk_tinp_base"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["int_snaps.id"], name="fk_tinp_snap"),
        sa.ForeignKeyConstraint(["capture_id"], ["topo_captures.id"], name="fk_tinp_cap"),
        sa.ForeignKeyConstraint(["captured_by_id"], ["actors.id"], name="fk_tinp_actor"),
        sa.PrimaryKeyConstraint("id", name="pk_topo_inputs"),
        sa.UniqueConstraint("intake_id", "semantic_input_hash", name="uq_tinp_semantic"),
    )
    op.create_index("ix_tinp_intake", "topo_inputs", ["intake_id"])

    op.create_table(
        "gen_keys",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("semantic_input_hash", sa.CHAR(64), nullable=False),
        sa.Column("run_id", sa.CHAR(36), nullable=False),
        sa.Column("reservation_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_gkey_intake"),
        sa.ForeignKeyConstraint(["run_id"], ["gen_runs.id"], name="fk_gkey_run"),
        sa.PrimaryKeyConstraint("id", name="pk_gen_keys"),
        sa.UniqueConstraint("intake_id", "semantic_input_hash", name="uq_gkey_semantic"),
    )
    op.create_index("ix_gkey_run", "gen_keys", ["run_id"])

    op.create_table(
        "topo_reviews",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.CHAR(36), nullable=False),
        sa.Column("run_id", sa.CHAR(36), nullable=True),
        sa.Column("base_artifact_id", sa.CHAR(36), nullable=True),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("compatibility_result_hash", sa.CHAR(64), nullable=True),
        sa.Column("manifest_hash", sa.CHAR(64), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("issue_decisions", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.CHAR(36), nullable=False),
        sa.Column("self_review", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_topo_reviews"),
    )
    op.create_index("ix_trev_entity", "topo_reviews", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_trev_entity", table_name="topo_reviews")
    op.drop_table("topo_reviews")
    op.drop_index("ix_gkey_run", table_name="gen_keys")
    op.drop_table("gen_keys")
    op.drop_index("ix_tinp_intake", table_name="topo_inputs")
    op.drop_table("topo_inputs")
    op.drop_index("ix_tcap_intake", table_name="topo_captures")
    op.drop_table("topo_captures")
    op.drop_index("ix_tcmp_base", table_name="topo_compat")
    op.drop_table("topo_compat")
    if op.get_bind().dialect.name == "oracle":
        op.drop_constraint("uq_gart_type", "gen_artifacts", type_="unique")
    else:
        with op.batch_alter_table("gen_artifacts", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_gart_type", type_="unique")
    op.drop_index("ix_gnrn_input", table_name="gen_runs")
    with op.batch_alter_table("gen_runs") as batch_op:
        for column in (
            "manifest_hash", "lease_expires_at", "lease_token", "attempt_number",
            "semantic_input_hash", "row_version", "phase", "authority", "capability",
            "mode", "input_id",
        ):
            batch_op.drop_column(column)
    with op.batch_alter_table("topo_base") as batch_op:
        for column in (
            "review_rationale", "reviewed_at", "reviewed_by_id", "compatibility_id",
            "selection_hash", "selection_json", "capability", "profile_hash",
            "profile_version", "profile_id", "lifecycle", "authority", "row_version",
        ):
            batch_op.drop_column(column)
