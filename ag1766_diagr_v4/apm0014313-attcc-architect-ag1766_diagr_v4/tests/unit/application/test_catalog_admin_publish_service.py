"""
Tests for CatalogAdminPublishService — CAT-B3.

Uses the same ``tmp_engine``/``session_factory`` fixtures as other
application-service tests (``tests/unit/application/conftest.py``), which
build an isolated, file-based SQLite database from ORM metadata for each
test — never via Alembic (see this repo's known Alembic/.env
DATABASE_URL-clobbering issue) and never against the real ``local.db``.
"""

from __future__ import annotations

import pytest

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import CatalogVersionConflictError
from migration_intake.application.services.catalog_admin_publish import (
    CatalogAdminPublishService,
    CatalogCompileError,
)
from migration_intake.persistence.unit_of_work import uow_context

CSV_HEADER = (
    "Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,"
    "Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination"
)
ROW_CTL_001 = (
    "CTL-001,CTL,What is the correlation ID?,IDENTIFIER,,REQUIRED,,Workbook,,"
    "Application Owner,ALL,ANSWER"
)
ROW_DB_001 = (
    "DB-001,DB,Does the application use a database?,BOOLEAN,YES|NO|UNKNOWN,"
    "REQUIRED,,Workbook|iTAP,,Application Owner,Topology,ANSWER"
)


def make_csv(*rows: str) -> bytes:
    """Build CSV content (as uploaded bytes) from header + data rows."""
    return "\n".join((CSV_HEADER, *rows)).encode("utf-8")


VALID_CSV = make_csv(ROW_CTL_001)
VALID_CSV_DIFFERENT_CONTENT = make_csv(ROW_CTL_001, ROW_DB_001)
INVALID_CSV_DUPLICATE_ID = make_csv(ROW_CTL_001, ROW_CTL_001)


def _actor() -> ActorContext:
    return ActorContext(actor_id="test-actor")


def _release_count(session_factory) -> int:
    with uow_context(session_factory) as uow:
        return len(uow.catalogs.list_releases())


class TestPreview:
    """preview() compiles but never touches the database."""

    def test_valid_csv_previews_clean(self, session_factory) -> None:
        service = CatalogAdminPublishService(session_factory)

        result = service.preview(VALID_CSV, "catalog.csv", "1.0.0")

        assert result.release is not None
        assert result.report.is_success is True
        assert result.report.section_count >= 1
        assert result.report.question_count == 1

    def test_valid_csv_preview_creates_no_release_row(self, session_factory) -> None:
        service = CatalogAdminPublishService(session_factory)

        before = _release_count(session_factory)
        service.preview(VALID_CSV, "catalog.csv", "1.0.0")
        after = _release_count(session_factory)

        assert after == before == 0

    def test_invalid_csv_reports_diagnostics(self, session_factory) -> None:
        service = CatalogAdminPublishService(session_factory)

        result = service.preview(INVALID_CSV_DUPLICATE_ID, "catalog.csv", "1.0.0")

        assert result.release is None
        assert result.report.is_success is False
        assert result.report.diagnostics.has_errors() is True


class TestPublish:
    """publish() re-compiles internally and never trusts a prior preview()."""

    def test_valid_csv_publishes_new_release(self, session_factory) -> None:
        service = CatalogAdminPublishService(session_factory)

        release = service.publish(VALID_CSV, "catalog.csv", "1.0.0", _actor())

        assert release["semantic_version"] == "1.0.0"
        assert release["pub_state"] == "PUBLISHED"
        assert _release_count(session_factory) == 1

    def test_invalid_csv_publish_without_preview_raises_and_persists_nothing(
        self, session_factory
    ) -> None:
        """publish() must re-validate even if preview() was never called."""
        service = CatalogAdminPublishService(session_factory)

        with pytest.raises(CatalogCompileError) as exc_info:
            service.publish(INVALID_CSV_DUPLICATE_ID, "catalog.csv", "1.0.0", _actor())

        assert exc_info.value.diagnostics  # carries the diagnostics list
        assert _release_count(session_factory) == 0

    def test_reusing_version_with_different_content_raises_conflict(
        self, session_factory
    ) -> None:
        service = CatalogAdminPublishService(session_factory)
        service.publish(VALID_CSV, "catalog.csv", "1.0.0", _actor())

        with pytest.raises(CatalogVersionConflictError):
            service.publish(
                VALID_CSV_DIFFERENT_CONTENT, "catalog-v2.csv", "1.0.0", _actor()
            )

        # Existing release is untouched: still exactly one release, and its
        # hash/content still matches the original upload, not the conflicting one.
        with uow_context(session_factory) as uow:
            releases = uow.catalogs.list_releases()
            assert len(releases) == 1
            existing = uow.catalogs.get_release_by_version("1.0.0")
        assert existing is not None
        assert existing["source_filename"] == "catalog.csv"

    def test_republishing_identical_bytes_and_version_is_idempotent(
        self, session_factory
    ) -> None:
        service = CatalogAdminPublishService(session_factory)

        first = service.publish(VALID_CSV, "catalog.csv", "1.0.0", _actor())
        second = service.publish(VALID_CSV, "catalog.csv", "1.0.0", _actor())

        assert first["id"] == second["id"]
        assert _release_count(session_factory) == 1
