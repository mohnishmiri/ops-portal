"""
Catalog publication service — P05c/C04.

This service handles the publication of compiled catalog releases.
It ensures idempotency (same version+hash succeeds) and rejects
conflicting publications (same version, different hash).

Architecture rules applied here (sections 23-25.1, 27.1-27.2, 28):

- Receives validated catalog data; does NOT parse files or read env vars.
- Loads state through repositories inside a UoW.
- Commits through UoW.
- Returns detached plain dicts — no ORM entities leave this module.
- Does NOT swallow concurrency/integrity errors.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from migration_intake.application.errors import CatalogVersionConflictError
from migration_intake.persistence.unit_of_work import uow_context

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


class CatalogPublicationService:
    """
    Coordinates catalog release publication (P05c/C04).

    Each public method opens exactly one UoW, performs all reads and writes
    inside it, commits on success, and returns a plain dict.
    """

    def __init__(self, session_factory: sessionmaker[Any]) -> None:
        self._session_factory = session_factory

    def publish_release(
        self,
        semantic_version: str,
        source_filename: str,
        source_sha256: str,
        compiler_version: str,
        sections: list[dict[str, Any]],
        catalog_hash: str | None = None,
        compiler_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Publish a catalog release with sections and questions.

        Idempotency:
        - If a release with the same version AND source hash exists, return it.
        - If a release with the same version but different source hash exists, raise.
        - If a release with the same source hash but different catalog hash exists, raise.

        Args:
            semantic_version: Semantic version string (e.g., "1.0.0")
            source_filename: Original source file name
            source_sha256: SHA-256 hash of the source content
            catalog_hash: SHA-256 hash of the canonical compiled catalog
            compiler_version: Version of the catalog compiler
            sections: List of section dicts with questions
            compiler_report: Optional compiler report

        Returns:
            Dict with release details including id, pub_state, etc.

        Raises:
            CatalogVersionConflictError: Same version exists with different hash
        """
        # Older callers did not provide a compiled-catalog hash. Keep those
        # callers compatible while ensuring the persisted identity is stable.
        if catalog_hash is None:
            catalog_hash = source_sha256

        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            # Check for existing release with same version+hash (idempotent)
            existing = uow.catalogs.get_release_by_version_and_hash(
                semantic_version, source_sha256
            )
            if existing is not None:
                if (
                    existing.get("catalog_hash") != catalog_hash
                    or existing.get("compiler_version") != compiler_version
                ):
                    raise CatalogVersionConflictError(
                        f"Catalog version {semantic_version} with source hash "
                        f"{source_sha256} already exists with a different compiled "
                        "contract or compiler version"
                    )
                # Already published with the complete same identity — idempotent success
                return existing

            # Check for conflicting release (same version, different source hash)
            conflicting = uow.catalogs.get_release_by_version(semantic_version)
            if conflicting is not None:
                if conflicting["source_sha256"] != source_sha256:
                    raise CatalogVersionConflictError(
                        f"Catalog version {semantic_version} already exists with "
                        f"different source hash. Existing: {conflicting['source_sha256']}, "
                        f"New: {source_sha256}"
                    )
                # Same source hash but different catalog hash is also a conflict
                if conflicting.get("catalog_hash") and conflicting["catalog_hash"] != catalog_hash:
                    raise CatalogVersionConflictError(
                        f"Catalog version {semantic_version} with source hash {source_sha256} "
                        f"already exists with different catalog hash. "
                        f"Existing: {conflicting['catalog_hash']}, New: {catalog_hash}"
                    )

            # Create new release
            release_id = str(uuid.uuid4())
            uow.catalogs.add_release(
                release_id=release_id,
                semantic_version=semantic_version,
                source_filename=source_filename,
                source_sha256=source_sha256,
                catalog_hash=catalog_hash,
                compiler_version=compiler_version,
                pub_state="DRAFT",
                created_at=now,
                compiler_report=compiler_report,
            )

            # Add sections and questions
            for section_data in sections:
                section_id = str(uuid.uuid4())
                uow.catalogs.add_section(
                    section_id=section_id,
                    release_id=release_id,
                    section_code=section_data["section_code"],
                    display_name=section_data["display_name"],
                    display_order=section_data["display_order"],
                )

                for question_data in section_data.get("questions", []):
                    question_id = str(uuid.uuid4())
                    self._add_question_with_options(uow, question_id, section_id, question_data)

            # Mark as published
            uow.catalogs.publish_release(release_id, now)
            uow.commit()

            # Return the published release
            return uow.catalogs.get_release(release_id)  # type: ignore[return-value]

    @staticmethod
    def _add_question_with_options(
        uow: Any, question_id: str, section_id: str, question_data: dict[str, Any]
    ) -> None:
        """
        Persist one question and its allowed values.

        A controlled question whose options are dropped renders an empty
        editor, so the compiled vocabulary is written alongside the question
        rather than discarded at this boundary.
        """
        uow.catalogs.add_question(
            question_id=question_id,
            section_id=section_id,
            question_code=question_data["question_code"],
            question_text=question_data["question_text"],
            response_type=question_data["response_type"],
            required_level=question_data["required_level"],
            collection_mode=question_data["collection_mode"],
            display_order=question_data["display_order"],
            condition_ast=question_data.get("condition_ast"),
            is_active=question_data.get("is_active", True),
            help_text=question_data.get("help_text"),
            units=question_data.get("units"),
            field_name=question_data.get("field_name"),
            response_schema_version=question_data.get("response_schema_version"),
        )

        for order, option in enumerate(question_data.get("options") or [], start=1):
            uow.catalogs.add_option(
                option_id=str(uuid.uuid4()),
                question_id=question_id,
                option_code=option["code"],
                display_label=option.get("label") or option["code"],
                display_order=order,
            )

    def get_latest_published(self) -> dict[str, Any] | None:
        """
        Get the most recently published catalog release.

        Returns:
            Dict with release details, or None if no releases are published.
        """
        with uow_context(self._session_factory) as uow:
            return uow.catalogs.get_latest_published_release()
