"""
CatalogRepository — P04 (Repositories and Unit of Work).

CatalogRelease has no FK dependencies, making it the simplest write target
in tests and integration scenarios.  Sections and questions carry FK chains
back to the release.

Design rules (Architecture sections 31, 38):
- Returns plain dicts, never ORM entity instances.
- No independent session management; session is owned by UnitOfWork.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, select

from migration_intake.persistence.models import (
    CatalogOption,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session


class CatalogRepository:
    """Persistence adapter for catalog releases, sections, and questions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------

    def add_release(
        self,
        release_id: str,
        semantic_version: str,
        source_filename: str,
        source_sha256: str,
        compiler_version: str,
        pub_state: str,
        created_at: datetime,
        catalog_hash: str | None = None,
        compiler_report: dict[str, Any] | None = None,
    ) -> str:
        """Insert a catalog release row. Returns ``release_id``."""
        release = CatalogRelease(
            id=release_id,
            semantic_version=semantic_version,
            source_filename=source_filename,
            source_sha256=source_sha256,
            catalog_hash=catalog_hash or source_sha256,
            compiler_version=compiler_version,
            pub_state=pub_state,
            compiler_report=compiler_report,
            created_at=created_at,
        )
        self._session.add(release)
        self._session.flush()
        return release_id

    def get_release(self, release_id: str) -> dict[str, Any] | None:
        """Return a catalog release as a plain dict, or None if not found."""
        stmt = select(CatalogRelease).where(CatalogRelease.id == release_id)
        release = self._session.execute(stmt).scalar_one_or_none()
        if release is None:
            return None
        return self._release_to_dict(release)

    def get_published_release(self, semantic_version: str) -> dict[str, Any] | None:
        """Return the first PUBLISHED catalog release for a given version string."""
        stmt = select(CatalogRelease).where(
            CatalogRelease.semantic_version == semantic_version,
            CatalogRelease.pub_state == "PUBLISHED",
        )
        release = self._session.execute(stmt).scalar_one_or_none()
        if release is None:
            return None
        return self._release_to_dict(release)

    def get_latest_published_release(self) -> dict[str, Any] | None:
        """Return the most recently published catalog release."""
        stmt = (
            select(CatalogRelease)
            .where(CatalogRelease.pub_state == "PUBLISHED")
            .order_by(CatalogRelease.published_at.desc())
            .limit(1)
        )
        release = self._session.execute(stmt).scalar_one_or_none()
        if release is None:
            return None
        return self._release_to_dict(release)

    def get_release_by_version_and_hash(
        self, semantic_version: str, source_sha256: str
    ) -> dict[str, Any] | None:
        """Return a release matching both version and source hash."""
        stmt = select(CatalogRelease).where(
            CatalogRelease.semantic_version == semantic_version,
            CatalogRelease.source_sha256 == source_sha256,
        )
        release = self._session.execute(stmt).scalar_one_or_none()
        if release is None:
            return None
        return self._release_to_dict(release)

    def get_release_by_version(self, semantic_version: str) -> dict[str, Any] | None:
        """Return any release with the given semantic version."""
        stmt = select(CatalogRelease).where(
            CatalogRelease.semantic_version == semantic_version,
        )
        release = self._session.execute(stmt).scalar_one_or_none()
        if release is None:
            return None
        return self._release_to_dict(release)

    def list_releases(self) -> list[dict[str, Any]]:
        """
        Return every catalog release regardless of ``pub_state``, newest-first.

        Ordered by ``published_at`` descending. Releases with no
        ``published_at`` (e.g. ``DRAFT``) have never been published and sort
        after every published release; among themselves they are ordered by
        ``created_at`` descending for a stable, deterministic order.
        """
        stmt = select(CatalogRelease).order_by(
            case((CatalogRelease.published_at.is_(None), 1), else_=0),
            CatalogRelease.published_at.desc(),
            CatalogRelease.created_at.desc(),
        )
        releases = self._session.execute(stmt).scalars().all()
        return [self._release_to_dict(r) for r in releases]

    def list_all_releases(self) -> list[dict[str, Any]]:
        """
        Return every catalog release (alias for list_releases for census compatibility).

        This method exists for explicit census/inventory use cases.
        """
        return self.list_releases()

    def publish_release(self, release_id: str, published_at: datetime) -> None:
        """Mark a release as PUBLISHED."""
        from sqlalchemy import update

        stmt = (
            update(CatalogRelease)
            .where(CatalogRelease.id == release_id)
            .values(pub_state="PUBLISHED", published_at=published_at)
        )
        self._session.execute(stmt)
        self._session.flush()

    def get_releases_with_null_catalog_hash(self) -> list[dict[str, Any]]:
        """Return all releases where catalog_hash is null (for backfill)."""
        stmt = select(CatalogRelease).where(CatalogRelease.catalog_hash.is_(None))
        releases = self._session.execute(stmt).scalars().all()
        return [self._release_to_dict(r) for r in releases]

    def update_catalog_hash(self, release_id: str, catalog_hash: str) -> None:
        """Backfill catalog_hash for a release with null hash."""
        from sqlalchemy import update

        stmt = (
            update(CatalogRelease)
            .where(
                CatalogRelease.id == release_id,
                CatalogRelease.catalog_hash.is_(None),  # Only update if still null
            )
            .values(catalog_hash=catalog_hash)
        )
        self._session.execute(stmt)
        self._session.flush()

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def add_section(
        self,
        section_id: str,
        release_id: str,
        section_code: str,
        display_name: str,
        display_order: int,
    ) -> str:
        """Insert a catalog section. Returns ``section_id``."""
        section = CatalogSection(
            id=section_id,
            release_id=release_id,
            section_code=section_code,
            display_name=display_name,
            display_order=display_order,
        )
        self._session.add(section)
        self._session.flush()
        return section_id

    def get_sections_for_release(self, release_id: str) -> list[dict[str, Any]]:
        """Return all sections for a release in ascending display_order."""
        stmt = (
            select(CatalogSection)
            .where(CatalogSection.release_id == release_id)
            .order_by(CatalogSection.display_order)
        )
        sections = self._session.execute(stmt).scalars().all()
        return [self._section_to_dict(s) for s in sections]

    def get_sections_for_intake(self, intake_id: str) -> list[dict[str, Any]]:
        """Return all sections for an intake's catalog in ascending display_order."""
        # First get the intake's catalog_id
        stmt = select(Intake.catalog_id).where(Intake.id == intake_id)
        catalog_id = self._session.execute(stmt).scalar_one_or_none()
        if catalog_id is None:
            return []
        return self.get_sections_for_release(str(catalog_id))

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def add_question(
        self,
        question_id: str,
        section_id: str,
        question_code: str,
        question_text: str,
        response_type: str,
        required_level: str,
        collection_mode: str,
        display_order: int,
        condition_ast: dict[str, Any] | None = None,
        is_active: bool = True,
        help_text: str | None = None,
        units: str | None = None,
        field_name: str | None = None,
        response_schema_version: str | None = None,
    ) -> str:
        """Insert a catalog question. Returns ``question_id``."""
        question = CatalogQuestion(
            id=question_id,
            section_id=section_id,
            question_code=question_code,
            question_text=question_text,
            response_type=response_type,
            required_level=required_level,
            collection_mode=collection_mode,
            display_order=display_order,
            condition_ast=condition_ast,
            is_active=is_active,
            help_text=help_text,
            units=units,
            field_name=field_name,
            response_schema_version=response_schema_version,
        )
        self._session.add(question)
        self._session.flush()
        return question_id

    def add_option(
        self,
        option_id: str,
        question_id: str,
        option_code: str,
        display_label: str,
        display_order: int,
    ) -> str:
        """Insert one allowed value for a controlled question. Returns ``option_id``."""
        option = CatalogOption(
            id=option_id,
            question_id=question_id,
            option_code=option_code,
            display_label=display_label,
            display_order=display_order,
        )
        self._session.add(option)
        self._session.flush()
        return option_id

    def get_options_for_question(self, question_id: str) -> list[dict[str, Any]]:
        """Return a question's allowed values in ascending display_order."""
        stmt = (
            select(CatalogOption)
            .where(CatalogOption.question_id == question_id)
            .order_by(CatalogOption.display_order)
        )
        options = self._session.execute(stmt).scalars().all()
        return [
            {
                "value": option.option_code,
                "label": option.display_label,
                "display_order": option.display_order,
            }
            for option in options
        ]

    def count_options_for_release(self, release_id: str) -> int:
        """Return how many allowed values exist across a release's questions."""
        stmt = (
            select(func.count())
            .select_from(CatalogOption)
            .join(CatalogQuestion, CatalogOption.question_id == CatalogQuestion.id)
            .join(CatalogSection, CatalogQuestion.section_id == CatalogSection.id)
            .where(CatalogSection.release_id == release_id)
        )
        return int(self._session.execute(stmt).scalar_one())

    def get_questions_for_section(self, section_id: str) -> list[dict[str, Any]]:
        """Return all questions for a section in ascending display_order."""
        stmt = (
            select(CatalogQuestion)
            .where(CatalogQuestion.section_id == section_id)
            .order_by(CatalogQuestion.display_order)
        )
        questions = self._session.execute(stmt).scalars().all()
        return [self._question_to_dict(q) for q in questions]

    def get_question_by_code(
        self, catalog_id: str, question_code: str
    ) -> dict[str, Any] | None:
        """
        Return a catalog question by its code within a given catalog release.

        Joins cat_questions → cat_sections on release_id to scope the lookup
        to the correct catalog release.  Returns None when not found.
        """
        stmt = (
            select(CatalogQuestion)
            .join(CatalogSection, CatalogQuestion.section_id == CatalogSection.id)
            .where(
                CatalogSection.release_id == catalog_id,
                CatalogQuestion.question_code == question_code,
            )
        )
        question = self._session.execute(stmt).scalar_one_or_none()
        if question is None:
            return None
        return self._question_to_dict(question)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _release_to_dict(release: CatalogRelease) -> dict[str, Any]:
        return {
            "id": str(release.id),
            "semantic_version": release.semantic_version,
            "source_filename": release.source_filename,
            "source_sha256": release.source_sha256,
            "compiler_version": release.compiler_version,
            "pub_state": release.pub_state,
            "published_at": release.published_at,
            "catalog_hash": release.catalog_hash,
            "compiler_report": release.compiler_report,
            "created_at": release.created_at,
        }

    @staticmethod
    def _section_to_dict(s: CatalogSection) -> dict[str, Any]:
        return {
            "id": str(s.id),
            "release_id": str(s.release_id),
            "section_code": s.section_code,
            "display_name": s.display_name,
            "display_order": s.display_order,
        }

    @staticmethod
    def _question_to_dict(q: CatalogQuestion) -> dict[str, Any]:
        return {
            "id": str(q.id),
            "section_id": str(q.section_id),
            "question_code": q.question_code,
            "question_text": q.question_text,
            "response_type": q.response_type,
            "required_level": q.required_level,
            "collection_mode": q.collection_mode,
            "display_order": q.display_order,
            "condition_ast": q.condition_ast,
            "is_active": q.is_active,
            "help_text": q.help_text,
            "units": q.units,
            "field_name": q.field_name,
            "response_schema_version": q.response_schema_version,
        }
