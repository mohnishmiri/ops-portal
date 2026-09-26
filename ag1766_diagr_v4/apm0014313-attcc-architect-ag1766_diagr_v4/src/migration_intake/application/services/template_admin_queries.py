"""Read-model queries for topology template admin pages."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from migration_intake.persistence.repositories.templates import TemplateRepository


class TemplateAdminQueryService:
    """Read-only query service for template release list/detail views."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_releases(self) -> list[dict[str, Any]]:
        session = self._session_factory()
        try:
            repo = TemplateRepository(session)
            rows = repo.list_releases()
            latest = repo.get_latest_published_release()
            latest_id = latest["id"] if latest else None
            return [
                {
                    **row,
                    "is_active": row["id"] == latest_id and row["pub_state"] == "PUBLISHED",
                }
                for row in rows
            ]
        finally:
            session.close()

    def get_release_detail(self, release_id: str) -> dict[str, Any] | None:
        try:
            uuid.UUID(release_id)
        except (ValueError, TypeError, AttributeError):
            return None

        session = self._session_factory()
        try:
            return TemplateRepository(session).get_release(release_id)
        finally:
            session.close()
