"""Core actors, applications, catalog releases/definitions, intakes, answers, audit.

Creates all 12 domain tables that form the initial schema for the Migration
Intake application (Architecture section 37 — P03 baseline migration).

Tables (dependency order):
  actors → applications → app_identifiers
  cat_releases → cat_sections → cat_questions → cat_options → cat_src_rels
  intakes
  ans_instances → ans_revisions  (circular FK broken with batch alter)
  audit_events

Physical column types follow the TypeDecorator impl types declared in
persistence/types.py:
  PortableUUID → CHAR(36)       (String(36) impl, stored as canonical UUID string)
  PortableUTC  → VARCHAR(32)    (String(32) impl, stored as ISO-8601 UTC text)
  Sha256Hex    → VARCHAR(64)    (String(64) impl, 64 hex chars)
  CanonicalJSON → TEXT          (Text impl, sorted-key JSON)

Constraint names match the ORM models exactly:
  PKs:  pk_%(table_name)s  (via NAMING_CONVENTION)
  UQs:  explicit or uq_%(table_name)s_%(column_0_name)s
  FKs:  explicit short names from __table_args__ in models.py
  IXs:  ix_audit_events_entity_type, ix_audit_events_occurred_at

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. actors
    #    No foreign keys; referenced by applications, intakes, ans_revisions,
    #    audit_events (actor_id is a bare UUID — no FK on audit_events).
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "actors",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("attuid", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_actors"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 2. applications   FK → actors
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "applications",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_appl_act",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_applications"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 3. app_identifiers   FK → applications
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "app_identifiers",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("identifier_type", sa.String(64), nullable=False),
        sa.Column("raw_value", sa.String(255), nullable=False),
        sa.Column("normalized_value", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_appi_appl",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_app_identifiers"),
        # uq_%(table_name)s_%(column_0_name)s → uq_appi_itype_norm (explicit)
        sa.UniqueConstraint(
            "identifier_type",
            "normalized_value",
            name="uq_appi_itype_norm",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 4. cat_releases   No foreign keys
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "cat_releases",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("semantic_version", sa.String(32), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("compiler_version", sa.String(32), nullable=False),
        sa.Column("pub_state", sa.String(32), nullable=False),
        sa.Column("published_at", sa.String(32), nullable=True),
        sa.Column("catalog_hash", sa.String(64), nullable=True),
        sa.Column("compiler_report", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_cat_releases"),
        # auto-name: uq_cat_releases_source_sha256 (column_0_name = source_sha256)
        sa.UniqueConstraint("source_sha256", name="uq_cat_releases_source_sha256"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 5. cat_sections   FK → cat_releases
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "cat_sections",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("release_id", sa.CHAR(36), nullable=False),
        sa.Column("section_code", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["cat_releases.id"],
            name="fk_csec_crel",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cat_sections"),
        # auto-name: uq_cat_sections_release_id (column_0_name = release_id)
        sa.UniqueConstraint(
            "release_id",
            "section_code",
            name="uq_cat_sections_release_id",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 6. cat_questions   FK → cat_sections
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "cat_questions",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("section_id", sa.CHAR(36), nullable=False),
        sa.Column("question_code", sa.String(64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("response_type", sa.String(64), nullable=False),
        sa.Column("required_level", sa.String(32), nullable=False),
        sa.Column("collection_mode", sa.String(32), nullable=False),
        sa.Column("condition_ast", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("help_text", sa.Text(), nullable=True),
        sa.Column("units", sa.String(32), nullable=True),
        sa.Column("field_name", sa.String(64), nullable=True),
        sa.Column("response_schema_version", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["cat_sections.id"],
            name="fk_cq_csec",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cat_questions"),
        # auto-name: uq_cat_questions_section_id (column_0_name = section_id)
        sa.UniqueConstraint(
            "section_id",
            "question_code",
            name="uq_cat_questions_section_id",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 7. cat_options   FK → cat_questions
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "cat_options",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("question_id", sa.CHAR(36), nullable=False),
        sa.Column("option_code", sa.String(64), nullable=False),
        sa.Column("display_label", sa.String(255), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["cat_questions.id"],
            name="fk_copt_cq",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cat_options"),
        # auto-name: uq_cat_options_question_id (column_0_name = question_id)
        sa.UniqueConstraint(
            "question_id",
            "option_code",
            name="uq_cat_options_question_id",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 8. cat_src_rels   FK → cat_questions
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "cat_src_rels",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("question_id", sa.CHAR(36), nullable=False),
        sa.Column("source_label", sa.String(128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["cat_questions.id"],
            name="fk_csr_cq",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cat_src_rels"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 9. intakes   FK → applications, cat_releases, actors
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "intakes",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        sa.Column("catalog_id", sa.CHAR(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_intk_appl",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_id"],
            ["cat_releases.id"],
            name="fk_intk_crel",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_intk_act",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intakes"),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 10. ans_instances   FK → intakes, cat_questions
    #     NOTE: the circular FK to ans_revisions (fk_ainst_arev) is added
    #     AFTER ans_revisions is created (see step 12 below) using a
    #     batch_alter_table to satisfy SQLite's DDL limitations.
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "ans_instances",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("intake_id", sa.CHAR(36), nullable=False),
        sa.Column("question_id", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        # Nullable: resolved after first revision is inserted (cycle-breaker).
        sa.Column("current_rev_id", sa.CHAR(36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_ainst_intk",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["cat_questions.id"],
            name="fk_ainst_cq",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ans_instances"),
        # auto-name: uq_ans_instances_intake_id (column_0_name = intake_id)
        sa.UniqueConstraint(
            "intake_id",
            "question_id",
            name="uq_ans_instances_intake_id",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 11. ans_revisions   FK → ans_instances, actors
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "ans_revisions",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("instance_id", sa.CHAR(36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("confirm_state", sa.String(32), nullable=False),
        sa.Column("authored_at", sa.String(32), nullable=False),
        sa.Column("authored_by_id", sa.CHAR(36), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("response_schema_version", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["ans_instances.id"],
            name="fk_arev_ainst",
        ),
        sa.ForeignKeyConstraint(
            ["authored_by_id"],
            ["actors.id"],
            name="fk_arev_act",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ans_revisions"),
        # auto-name: uq_ans_revisions_instance_id (column_0_name = instance_id)
        sa.UniqueConstraint(
            "instance_id",
            "revision_number",
            name="uq_ans_revisions_instance_id",
        ),
    )

    # ─────────────────────────────────────────────────────────────────────
    # 12. Close the cycle: add fk_ainst_arev  (ans_instances → ans_revisions)
    #     Use batch_alter_table because SQLite does not support
    #     ALTER TABLE ... ADD CONSTRAINT.
    # ─────────────────────────────────────────────────────────────────────
    with op.batch_alter_table("ans_instances", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_ainst_arev",
            "ans_revisions",
            ["current_rev_id"],
            ["id"],
        )

    # ─────────────────────────────────────────────────────────────────────
    # 13. audit_events   No FK constraints (entity_id / actor_id are bare UUIDs)
    # ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.CHAR(36), nullable=False),
        sa.Column("event_code", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.CHAR(36), nullable=True),
        sa.Column("occurred_at", sa.String(32), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )

    # Explicit indexes on audit_events (named in ORM __table_args__)
    op.create_index(
        "ix_audit_events_entity_type",
        "audit_events",
        ["entity_type", "entity_id"],
    )
    op.create_index(
        "ix_audit_events_occurred_at",
        "audit_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # Drop in reverse dependency order.
    # Break the circular FK first so ans_instances can be dropped before
    # ans_revisions without violating referential integrity.
    # ─────────────────────────────────────────────────────────────────────

    # 1. Remove indexes on audit_events
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_type", table_name="audit_events")

    # 2. Drop audit_events (no incoming FK references)
    op.drop_table("audit_events")

    # 3. Break the circular FK before dropping either ans table
    with op.batch_alter_table("ans_instances", schema=None) as batch_op:
        batch_op.drop_constraint("fk_ainst_arev", type_="foreignkey")

    # 4. Drop ans_revisions (FK → ans_instances, actors)
    op.drop_table("ans_revisions")

    # 5. Drop ans_instances (FK → intakes, cat_questions)
    op.drop_table("ans_instances")

    # 6. Drop intakes (FK → applications, cat_releases, actors)
    op.drop_table("intakes")

    # 7. Drop cat_src_rels (FK → cat_questions)
    op.drop_table("cat_src_rels")

    # 8. Drop cat_options (FK → cat_questions)
    op.drop_table("cat_options")

    # 9. Drop cat_questions (FK → cat_sections)
    op.drop_table("cat_questions")

    # 10. Drop cat_sections (FK → cat_releases)
    op.drop_table("cat_sections")

    # 11. Drop cat_releases (no more incoming FKs)
    op.drop_table("cat_releases")

    # 12. Drop app_identifiers (FK → applications)
    op.drop_table("app_identifiers")

    # 13. Drop applications (FK → actors)
    op.drop_table("applications")

    # 14. Drop actors (nothing points to it now)
    op.drop_table("actors")
