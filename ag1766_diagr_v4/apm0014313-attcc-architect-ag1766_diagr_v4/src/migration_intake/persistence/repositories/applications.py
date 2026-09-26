"""
ApplicationRepository — P04 (Repositories and Unit of Work).

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- Methods accept domain-typed arguments (str UUIDs, datetime, str states).
- Optimistic concurrency via row_version predicate; rowcount check, not exception.
- Session is owned by the UnitOfWork; no independent commits here.
- Import models at module level to avoid circular import with the package __init__.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from migration_intake.persistence.models import Application, ApplicationIdentifier


class ApplicationRepository:
    """
    Persistence adapter for the Application aggregate.

    All methods operate on the session provided at construction time.
    The owning UnitOfWork controls when/whether to commit.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(
        self,
        actor_id: str,
        display_name: str,
        state: str,
        created_at: datetime,
        application_id: str | None = None,
    ) -> str:
        """
        Insert a new application row and return its UUID string.

        If ``application_id`` is not supplied a fresh UUID is generated.
        ``updated_at`` defaults to ``created_at``; ``row_version`` starts at 1.
        """
        if application_id is None:
            application_id = str(uuid.uuid4())

        app = Application(
            id=application_id,
            state=state,
            display_name=display_name,
            created_at=created_at,
            updated_at=created_at,
            row_version=1,
            created_by_id=actor_id,
        )
        self._session.add(app)
        self._session.flush()
        return application_id

    def add_identifier(
        self,
        application_id: str,
        identifier_type: str,
        raw_value: str,
        normalized_value: str,
        created_at: datetime,
    ) -> str:
        """
        Add an external identifier for an application.

        The UNIQUE(identifier_type, normalized_value) constraint on
        ``app_identifiers`` is enforced by the database; callers should
        catch ``sqlalchemy.exc.IntegrityError`` on duplicate inserts.
        """
        identifier_id = str(uuid.uuid4())
        ident = ApplicationIdentifier(
            id=identifier_id,
            application_id=application_id,
            identifier_type=identifier_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            created_at=created_at,
        )
        self._session.add(ident)
        self._session.flush()
        return identifier_id

    def update_state(
        self,
        application_id: str,
        new_state: str,
        expected_version: int,
        updated_at: datetime,
    ) -> bool:
        """
        Atomically update application state using optimistic concurrency.

        Issues:
            UPDATE applications
               SET state       = :new_state,
                   row_version = row_version + 1,
                   updated_at  = :updated_at
             WHERE id          = :id
               AND row_version = :expected_version

        Returns:
            ``True`` if exactly one row was affected (update succeeded).
            ``False`` if zero rows were affected (stale version = concurrent conflict).
        """
        stmt = (
            update(Application)
            .where(
                Application.id == application_id,
                Application.row_version == expected_version,
            )
            .values(
                state=new_state,
                row_version=Application.row_version + 1,
                updated_at=updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        result = self._session.execute(stmt)
        return result.rowcount == 1

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, application_id: str) -> dict[str, Any] | None:
        """Return the application as a plain dict, or None if not found."""
        stmt = select(Application).where(Application.id == application_id)
        app = self._session.execute(stmt).scalar_one_or_none()
        if app is None:
            return None
        return self._to_dict(app)

    def get_for_update(self, application_id: str) -> dict[str, Any] | None:
        """Return an application under a dialect-supported row lock."""
        app = self._session.execute(
            select(Application)
            .where(Application.id == application_id)
            .with_for_update()
        ).scalar_one_or_none()
        return self._to_dict(app) if app is not None else None

    def get_by_normalized_identifier(
        self, identifier_type: str, normalized_value: str
    ) -> dict[str, Any] | None:
        """
        Find an application by its external identifier.

        Looks up the ``app_identifiers`` table by (identifier_type,
        normalized_value) then returns the owning application dict, or
        None when no match is found.
        """
        stmt = select(ApplicationIdentifier).where(
            ApplicationIdentifier.identifier_type == identifier_type,
            ApplicationIdentifier.normalized_value == normalized_value,
        )
        ident = self._session.execute(stmt).scalar_one_or_none()
        if ident is None:
            return None

        app_stmt = select(Application).where(
            Application.id == ident.application_id
        )
        app = self._session.execute(app_stmt).scalar_one_or_none()
        if app is None:
            return None
        return self._to_dict(app)

    def list_identifiers(self, application_id: str) -> list[dict[str, str]]:
        """Return external identifiers belonging to one application."""
        stmt = (
            select(ApplicationIdentifier)
            .where(ApplicationIdentifier.application_id == application_id)
            .order_by(ApplicationIdentifier.identifier_type.asc())
        )
        identifiers = self._session.execute(stmt).scalars().all()
        return [
            {
                "application_id": str(identifier.application_id),
                "identifier_type": identifier.identifier_type,
                "raw_value": identifier.raw_value,
                "normalized_value": identifier.normalized_value,
            }
            for identifier in identifiers
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(app: Application) -> dict[str, Any]:
        """Convert an Application ORM row to a plain dict."""
        return {
            "id": str(app.id),
            "state": app.state,
            "display_name": app.display_name,
            "created_at": app.created_at,
            "updated_at": app.updated_at,
            "row_version": app.row_version,
            "interface_epoch": app.interface_epoch,
            "created_by_id": str(app.created_by_id),
        }
