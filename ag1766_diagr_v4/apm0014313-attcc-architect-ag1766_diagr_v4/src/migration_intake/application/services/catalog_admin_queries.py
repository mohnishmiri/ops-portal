"""
Read-only catalog admin query service — CAT-B1.

Provides the read model an admin catalog-viewer UI needs: every release
(any ``pub_state``) decorated with which one is latest-published and how
many intakes are pinned to it, plus a full section/question detail tree for
a single release.

Design rules (matches ``ImportCoverageService``):
- Plain dicts out, never ORM entities.
- One session per public method, closed in a ``finally`` block.
- Section/question traversal reuses the exact repository methods the
  questionnaire read path already uses (``get_sections_for_release`` /
  ``get_questions_for_section``) so admin output can never drift from what
  questionnaire actually renders.
- "Latest" is never recomputed here; it always defers to
  ``CatalogRepository.get_latest_published_release()`` as the single source
  of truth.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository


class CatalogAdminQueryService:
    """Read model for the catalog admin viewer: releases, pins, and detail trees."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def list_releases(self) -> list[dict[str, Any]]:
        """
        Return every catalog release, newest-first.

        Each release dict from ``CatalogRepository.list_releases()`` is
        decorated with:
        - ``is_latest``: True for exactly the release returned by
          ``get_latest_published_release()``, False for all others.
        - ``pinned_intake_count``: exact count of intakes with that
          release's id as their ``catalog_id``.
        """
        session = self._session_factory()
        try:
            catalogs = CatalogRepository(session)
            intakes = IntakeRepository(session)

            releases = catalogs.list_releases()
            latest = catalogs.get_latest_published_release()
            latest_id = latest["id"] if latest is not None else None

            return [
                {
                    **release,
                    "is_latest": release["id"] == latest_id,
                    "pinned_intake_count": intakes.count_by_catalog_id(release["id"]),
                }
                for release in releases
            ]
        finally:
            session.close()

    def get_release_detail(self, release_id: str) -> dict[str, Any] | None:
        """
        Return the full section/question tree for one release, or None.

        Sections and questions are traversed with the same
        ``get_sections_for_release`` / ``get_questions_for_section`` calls
        the questionnaire read path uses, so ordering can never diverge.

        A ``release_id`` that isn't even a well-formed UUID is treated the
        same as "not found" rather than raising: the ``id`` column is a
        ``PortableUUID`` that validates its input at bind-parameter time, so
        an unguarded query would otherwise surface as an unhandled 500
        instead of the 404 an unknown-but-well-formed id already produces.
        """
        try:
            uuid.UUID(release_id)
        except (ValueError, AttributeError, TypeError):
            return None

        session = self._session_factory()
        try:
            catalogs = CatalogRepository(session)
            release = catalogs.get_release(release_id)
            if release is None:
                return None

            sections = []
            for section in catalogs.get_sections_for_release(release_id):
                questions = catalogs.get_questions_for_section(section["id"])
                sections.append({**section, "questions": questions})

            pinned_intake_count = IntakeRepository(session).count_by_catalog_id(
                release_id
            )

            return {
                "id": release["id"],
                "semantic_version": release["semantic_version"],
                "source_filename": release["source_filename"],
                "pub_state": release["pub_state"],
                "published_at": release["published_at"],
                "compiler_report": release["compiler_report"],
                "pinned_intake_count": pinned_intake_count,
                "sections": sections,
            }
        finally:
            session.close()
