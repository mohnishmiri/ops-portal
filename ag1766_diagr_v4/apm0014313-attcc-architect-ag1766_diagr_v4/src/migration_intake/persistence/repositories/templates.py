"""Repository for topology template release records."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, select

from migration_intake.persistence.models_templates import TemplateRelease

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TemplateRepository:
    """Persistence adapter for template release metadata."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_release(
        self,
        *,
        release_id: str,
        template_version: str,
        source_filename: str,
        source_sha256: str,
        content_address: str,
        size_bytes: int,
        tab_count: int,
        variant_manifest: list[dict[str, Any]],
        compiler_version: str,
        compiler_report: dict[str, Any] | None,
        pub_state: str,
        published_at: datetime | None,
        published_by_id: str | None,
        created_at: datetime,
    ) -> dict[str, Any]:
        row = TemplateRelease(
            id=release_id,
            template_version=template_version,
            source_filename=source_filename,
            source_sha256=source_sha256,
            content_address=content_address,
            size_bytes=size_bytes,
            tab_count=tab_count,
            variant_manifest=variant_manifest,
            compiler_version=compiler_version,
            compiler_report=compiler_report,
            pub_state=pub_state,
            published_at=published_at,
            published_by_id=published_by_id,
            retired_at=None,
            created_at=created_at,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_dict(row)

    def get_release(self, release_id: str) -> dict[str, Any] | None:
        row = self._session.execute(
            select(TemplateRelease).where(TemplateRelease.id == release_id)
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def list_releases(self) -> list[dict[str, Any]]:
        rows = self._session.execute(
            select(TemplateRelease).order_by(
                case((TemplateRelease.published_at.is_(None), 1), else_=0),
                TemplateRelease.published_at.desc(),
                TemplateRelease.created_at.desc(),
            )
        ).scalars().all()
        return [self._to_dict(row) for row in rows]

    def get_latest_published_release(self) -> dict[str, Any] | None:
        row = self._session.execute(
            select(TemplateRelease)
            .where(TemplateRelease.pub_state == "PUBLISHED")
            .order_by(TemplateRelease.published_at.desc(), TemplateRelease.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def get_release_by_version(self, template_version: str) -> dict[str, Any] | None:
        row = self._session.execute(
            select(TemplateRelease).where(
                TemplateRelease.template_version == template_version
            )
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def get_release_by_version_and_hash(
        self, template_version: str, source_sha256: str
    ) -> dict[str, Any] | None:
        row = self._session.execute(
            select(TemplateRelease).where(
                TemplateRelease.template_version == template_version,
                TemplateRelease.source_sha256 == source_sha256,
            )
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def update_pub_state(
        self,
        release_id: str,
        *,
        pub_state: str,
        published_at: datetime | None = None,
        published_by_id: str | None = None,
        retired_at: datetime | None = None,
    ) -> dict[str, Any]:
        row = self._session.execute(
            select(TemplateRelease).where(TemplateRelease.id == release_id)
        ).scalar_one()
        row.pub_state = pub_state
        if published_at is not None:
            row.published_at = published_at
        if published_by_id is not None:
            row.published_by_id = published_by_id
        if retired_at is not None:
            row.retired_at = retired_at
        self._session.flush()
        return self._to_dict(row)

    def _to_dict(self, row: TemplateRelease) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "template_version": row.template_version,
            "source_filename": row.source_filename,
            "source_sha256": row.source_sha256,
            "content_address": row.content_address,
            "size_bytes": row.size_bytes,
            "tab_count": row.tab_count,
            "variant_manifest": row.variant_manifest,
            "compiler_version": row.compiler_version,
            "compiler_report": row.compiler_report,
            "pub_state": row.pub_state,
            "published_at": row.published_at,
            "published_by_id": str(row.published_by_id) if row.published_by_id else None,
            "retired_at": row.retired_at,
            "created_at": row.created_at,
        }
