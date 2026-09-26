"""Interface register — interfaces (single canonical table, no revision history).

Adds one domain table for the App Data Capture workbook's Interface sheet:
  interfaces — one row per counterpart interface for an application.
               Current-state only; row_version + updated_at/updated_by_id
               track the most recent write instead of an append-only
               revision table. All 33 Interface-sheet columns are captured
               verbatim (see docs/INTERFACE_REGISTER_DESIGN.md §3).

Two identifiers for the migrating application:
  application_id — internal FK to applications.id, ON DELETE CASCADE, so
                   deleting an application also removes its interfaces rows.
                   Never shown to a user.
  migrating_app_correlation_id — the sheet's own "Migrating App Correlation
                   ID" value (e.g. "18678"), stored verbatim; the
                   business-facing identifier used for sheet-row validation.
                   Not a native FK — Oracle cannot express a filtered-
                   composite reference to app_identifiers
                   (identifier_type='CORRELATION'); validated at the
                   service layer instead.

No uniqueness constraint on the natural key: the source sheet can contain
multiple distinct rows sharing the same interface_correlation_id. De-dup on
import compares every field (InterfaceRepository.find_exact_duplicate), not
just the key, so genuinely different rows are never collapsed together.

Physical column types follow the TypeDecorator impl types (same as 0001/0002):
  PortableUUID  → CHAR(36)     (String(36) impl)
  PortableUTC   → VARCHAR(32)  (String(32) impl)

All constraint names ≤ 30 characters (Oracle 12c conservative limit).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interfaces",
        sa.Column("id", sa.CHAR(36), nullable=False),
        # Internal FK — cascade-delete plumbing only, never user-facing.
        sa.Column("application_id", sa.CHAR(36), nullable=False),
        # Natural link to the migrating application (its own CORRELATION
        # identifier value, e.g. "18678") — not applications.id.
        sa.Column("migrating_app_correlation_id", sa.String(255), nullable=False),
        sa.Column("migrating_app_acronym", sa.String(255), nullable=True),
        sa.Column("consumer_or_provider", sa.String(64), nullable=True),
        # Natural key (not unique — see module docstring)
        sa.Column("interface_correlation_id", sa.String(255), nullable=False),
        sa.Column("interface_app_acronym", sa.String(255), nullable=True),
        sa.Column("interface_migration_wave", sa.String(255), nullable=True),
        sa.Column("interface_system_location", sa.String(255), nullable=True),
        sa.Column("end_point_name", sa.Text(), nullable=True),
        sa.Column("data_traffic_direction", sa.String(32), nullable=True),
        sa.Column("connection_owner", sa.String(255), nullable=True),
        sa.Column("sync_async", sa.String(32), nullable=True),
        sa.Column("current_protocol", sa.String(255), nullable=True),
        sa.Column("current_interface_type", sa.String(255), nullable=True),
        sa.Column("target_protocol", sa.String(255), nullable=True),
        sa.Column("target_interface_type", sa.String(255), nullable=True),
        sa.Column("interface_impact_change_type", sa.String(255), nullable=True),
        sa.Column("current_port", sa.String(32), nullable=True),
        sa.Column("future_port", sa.String(32), nullable=True),
        sa.Column("encrypted_solution_cloud", sa.String(16), nullable=True),
        sa.Column("low_latency_required", sa.String(16), nullable=True),
        sa.Column("throughput_volume_req", sa.String(255), nullable=True),
        sa.Column("att_architecture_validated", sa.String(16), nullable=True),
        sa.Column("listed_in_itap", sa.String(32), nullable=True),
        sa.Column("engagement_email_sent_on", sa.String(64), nullable=True),
        sa.Column("funding_template_sent", sa.String(64), nullable=True),
        sa.Column("interface_commitment_date", sa.String(64), nullable=True),
        sa.Column("interface_included_in_crp", sa.String(255), nullable=True),
        sa.Column("funding_approved_epic", sa.String(32), nullable=True),
        sa.Column("connectivity_tested", sa.String(16), nullable=True),
        sa.Column("uat_tested", sa.String(32), nullable=True),
        sa.Column("interface_contact", sa.Text(), nullable=True),
        sa.Column("interface_cutover_contact", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "state", sa.String(30), nullable=False, server_default=sa.text("'ACTIVE'")
        ),
        sa.Column(
            "origin", sa.String(16), nullable=False, server_default=sa.text("'MANUAL'")
        ),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by_id", sa.CHAR(36), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("updated_by_id", sa.CHAR(36), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], name="fk_irec_appl",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["actors.id"], name="fk_irec_cact"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["actors.id"], name="fk_irec_uact"),
        sa.PrimaryKeyConstraint("id", name="pk_interfaces"),
    )


def downgrade() -> None:
    op.drop_table("interfaces")

