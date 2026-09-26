"""
InterfaceRepository — interface register persistence.

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- Session is owned by the UnitOfWork; no independent commits here.
- Single canonical table (interfaces) — no revision history; a record is
  only ever updated in place via an explicit edit by ``record_id``
  (row_version/updated_at/updated_by_id bumped then); everything else is
  create-only.
- No natural-key uniqueness is enforced — the source Interface sheet can
  legitimately contain multiple distinct rows sharing the same
  ``interface_correlation_id`` (different directions/connections recorded
  under one shared counterpart ID). De-dup on import is by **exact,
  whole-row equality** (``find_exact_duplicate``) so genuinely different
  rows are never silently collapsed/overwritten into each other.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from migration_intake.persistence.models import Application
from migration_intake.persistence.models_interfaces import InterfaceRecord
from migration_intake.topology.guide_policy import PROJECTION_FIELDS

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: All 33 Interface-sheet business fields, in sheet column order. Shared by
#: create/update/dict-conversion so the field list only needs to change once.
INTERFACE_FIELD_NAMES = (
    "migrating_app_correlation_id",
    "migrating_app_acronym",
    "consumer_or_provider",
    "interface_correlation_id",
    "interface_app_acronym",
    "interface_migration_wave",
    "interface_system_location",
    "end_point_name",
    "data_traffic_direction",
    "connection_owner",
    "sync_async",
    "current_protocol",
    "current_interface_type",
    "target_protocol",
    "target_interface_type",
    "interface_impact_change_type",
    "current_port",
    "future_port",
    "encrypted_solution_cloud",
    "low_latency_required",
    "throughput_volume_req",
    "att_architecture_validated",
    "listed_in_itap",
    "engagement_email_sent_on",
    "funding_template_sent",
    "interface_commitment_date",
    "interface_included_in_crp",
    "funding_approved_epic",
    "connectivity_tested",
    "uat_tested",
    "interface_contact",
    "interface_cutover_contact",
    "notes",
)


class InterfaceRepository:
    """Persistence adapter for InterfaceRecord (interfaces) rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_record(
        self,
        *,
        record_id: str,
        application_id: str,
        fields: dict[str, Any],
        origin: str,
        created_at: datetime,
        created_by_id: str,
    ) -> dict[str, Any]:
        """
        Insert a new interfaces row.

        ``application_id`` is the internal FK (cascades on application
        delete); ``fields`` must contain every name in
        ``INTERFACE_FIELD_NAMES`` (missing keys default to ``None``).
        """
        record = InterfaceRecord(
            id=record_id,
            application_id=application_id,
            **{name: fields.get(name) for name in INTERFACE_FIELD_NAMES},
            state="ACTIVE",
            origin=origin,
            created_at=created_at,
            created_by_id=created_by_id,
            updated_at=created_at,
            updated_by_id=created_by_id,
            row_version=1,
        )
        self._session.add(record)
        self._bump_interface_epoch(application_id)
        self._session.flush()
        return self._to_dict(record)

    def update_record(
        self,
        *,
        record_id: str,
        fields: dict[str, Any],
        origin: str,
        updated_at: datetime,
        updated_by_id: str,
    ) -> None:
        """Update the canonical fields of an existing interfaces row in place."""
        stmt = (
            update(InterfaceRecord)
            .where(InterfaceRecord.id == record_id)
            .values(
                **{name: fields.get(name) for name in INTERFACE_FIELD_NAMES},
                origin=origin,
                updated_at=updated_at,
                updated_by_id=updated_by_id,
                row_version=InterfaceRecord.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        if getattr(result, "rowcount", 0) == 1:
            application_id = self._application_id_for_record(record_id)
            self._bump_interface_epoch(application_id)

    def retire_record(
        self, *, record_id: str, retired_at: datetime, retired_by_id: str
    ) -> None:
        """Retire an interfaces row (state=RETIRED)."""
        stmt = (
            update(InterfaceRecord)
            .where(InterfaceRecord.id == record_id)
            .values(
                state="RETIRED",
                updated_at=retired_at,
                updated_by_id=retired_by_id,
                row_version=InterfaceRecord.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        if getattr(result, "rowcount", 0) == 1:
            application_id = self._application_id_for_record(record_id)
            self._bump_interface_epoch(application_id)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        """Return the interfaces row as a plain dict, or None if not found."""
        stmt = select(InterfaceRecord).where(InterfaceRecord.id == record_id)
        record = self._session.execute(stmt).scalar_one_or_none()
        if record is None:
            return None
        return self._to_dict(record)

    def find_exact_duplicate(
        self, application_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Return an existing ACTIVE row for this application whose every
        business field exactly matches ``fields`` (blank/``None`` treated
        as equivalent, everything else compared as a trimmed exact string),
        or ``None`` if no such row exists.

        Two rows sharing the same ``interface_correlation_id`` but differing
        in any other field are **not** duplicates of each other — each is
        kept as its own row.
        """
        incoming = {
            name: (fields.get(name) or "").strip() for name in INTERFACE_FIELD_NAMES
        }
        stmt = select(InterfaceRecord).where(
            InterfaceRecord.application_id == application_id,
            InterfaceRecord.state == "ACTIVE",
        )
        for record in self._session.execute(stmt).scalars():
            if all(
                (getattr(record, name) or "").strip() == incoming[name]
                for name in INTERFACE_FIELD_NAMES
            ):
                return self._to_dict(record)
        return None

    def list_records_for_application(
        self, application_id: str, state: str = "ACTIVE"
    ) -> list[dict[str, Any]]:
        """Return all rows for the application, filtered by state (default ACTIVE)."""
        stmt = (
            select(InterfaceRecord)
            .where(
                InterfaceRecord.application_id == application_id,
                InterfaceRecord.state == state,
            )
            .order_by(InterfaceRecord.id)
        )
        records = self._session.execute(stmt).scalars().all()
        return [self._to_dict(r) for r in records]

    def capture_projection_rows(
        self, application_id: str, state: str = "ACTIVE"
    ) -> tuple[int, list[dict[str, Any]]]:
        """Read one deterministic allowlisted register view with its epoch."""
        application = self._session.execute(
            select(Application)
            .where(Application.id == application_id)
            .with_for_update()
        ).scalar_one_or_none()
        if application is None:
            raise ValueError("Application not found")
        rows = self.list_records_for_application(application_id, state)
        return int(application.interface_epoch), [
            {
                field: (
                    row[field].isoformat()
                    if isinstance(row[field], datetime)
                    else row[field]
                )
                for field in PROJECTION_FIELDS
            }
            for row in rows
        ]

    def _application_id_for_record(self, record_id: str) -> str:
        application_id = self._session.execute(
            select(InterfaceRecord.application_id).where(InterfaceRecord.id == record_id)
        ).scalar_one()
        return str(application_id)

    def _bump_interface_epoch(self, application_id: str) -> None:
        self._session.execute(
            update(Application)
            .where(Application.id == application_id)
            .values(interface_epoch=Application.interface_epoch + 1)
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(record: InterfaceRecord) -> dict[str, Any]:
        return {
            "id": str(record.id),
            "application_id": str(record.application_id),
            **{name: getattr(record, name) for name in INTERFACE_FIELD_NAMES},
            "state": record.state,
            "origin": record.origin,
            "created_at": record.created_at,
            "created_by_id": str(record.created_by_id),
            "updated_at": record.updated_at,
            "updated_by_id": str(record.updated_by_id),
            "row_version": record.row_version,
        }

