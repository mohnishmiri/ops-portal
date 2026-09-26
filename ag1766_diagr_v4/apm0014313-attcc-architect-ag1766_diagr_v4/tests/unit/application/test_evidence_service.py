"""
Unit tests for EvidenceService — E02 evidence upload and query.

TDD RED → GREEN:
  Write tests first (they fail on ImportError until the service is implemented).

Fixtures ``tmp_engine`` and ``session_factory`` come from conftest.py.

Side-effect imports at module level ensure both ORM layers are registered in
Base.metadata BEFORE conftest.tmp_engine calls Base.metadata.create_all().
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone

import pytest

# --- side-effect: register EvidenceItem, WaveUtilRow, WaveUtilRevision in Base ---
import migration_intake.persistence.models_evidence  # noqa: F401

# --- imports under test (these will raise ImportError until implemented) -------
from migration_intake.application.errors import (
    EvidenceMediaTypeNotAllowedError,
    EvidenceTooLargeError,
)
from migration_intake.application.services.evidence import EvidenceService
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
)
from migration_intake.application.dto import ActorContext
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.persistence.unit_of_work import uow_context
from migration_intake.storage.filesystem import FilesystemStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_OCTET_STREAM = "application/octet-stream"


def _make_actor() -> ActorContext:
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
        actor_type="CONFIGURED",
    )


def _make_stream(content: bytes = b"fake xlsx content") -> io.BytesIO:
    return io.BytesIO(content)


def _create_app(session_factory, actor: ActorContext) -> str:
    """Create an application + actor row via ApplicationService; return app_id."""
    svc = ApplicationService(session_factory)
    result = svc.create_application(
        CreateApplicationCommand(
            display_name="Test App",
            identifiers=(),
            actor=actor,
        )
    )
    return result["id"]


def _create_catalog_release(session_factory) -> str:
    """Insert a minimal PUBLISHED catalog release row; return its id."""
    release_id = str(uuid.uuid4())
    sha256 = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    now = datetime.now(tz=timezone.utc)
    with uow_context(session_factory) as uow:
        uow.catalogs.add_release(
            release_id=release_id,
            semantic_version="1.0.0",
            source_filename="test-catalog.yaml",
            source_sha256=sha256,
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            created_at=now,
        )
        uow.commit()
    return release_id


def _create_intake(session_factory, actor: ActorContext, app_id: str) -> str:
    """Create a DRAFT intake for the given app; return intake_id."""
    cat_id = _create_catalog_release(session_factory)
    svc = ApplicationService(session_factory)
    result = svc.create_intake(
        CreateIntakeCommand(
            application_id=app_id,
            catalog_release_id=cat_id,
            actor=actor,
        )
    )
    return result["id"]


def _make_service(session_factory, tmp_path) -> EvidenceService:
    store = FilesystemStore(tmp_path / "evidence_store")
    return EvidenceService(session_factory, store)


# ---------------------------------------------------------------------------
# Upload evidence tests
# ---------------------------------------------------------------------------


class TestUploadEvidence:
    """UploadEvidence command — E02 section 25.3."""

    def test_upload_stores_bytes_and_returns_evidence_id(
        self, session_factory, tmp_path
    ) -> None:
        """Upload small XLSX → evidence_id present in result, is a valid UUID."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)

        content = b"PK\x03\x04fake xlsx bytes"
        stream = _make_stream(content)

        result = svc.upload_evidence(
            stream=stream,
            filename="report.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=app_id,
            intake_id=None,
            actor=actor,
        )

        assert "evidence_id" in result
        uuid.UUID(result["evidence_id"])  # must be a valid UUID
        assert "storage_key" in result
        assert "sha256_hex" in result
        assert result["deduplicated"] is False

    def test_upload_returns_sha256_in_result(
        self, session_factory, tmp_path
    ) -> None:
        """sha256_hex in result must match hashlib.sha256 of the uploaded bytes."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)

        content = b"deterministic content for sha256 check"
        expected_sha256 = hashlib.sha256(content).hexdigest()

        result = svc.upload_evidence(
            stream=_make_stream(content),
            filename="data.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=app_id,
            intake_id=None,
            actor=actor,
        )

        assert result["sha256_hex"] == expected_sha256

    def test_upload_deduplicates_content(
        self, session_factory, tmp_path
    ) -> None:
        """Uploading the same bytes twice → second call returns deduplicated=True with same evidence_id."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)

        content = b"duplicate content bytes for dedup test"

        first = svc.upload_evidence(
            stream=_make_stream(content),
            filename="file.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=app_id,
            intake_id=None,
            actor=actor,
        )

        second = svc.upload_evidence(
            stream=_make_stream(content),
            filename="file.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=app_id,
            intake_id=None,
            actor=actor,
        )

        assert second["deduplicated"] is True
        assert second["evidence_id"] == first["evidence_id"]
        assert second["storage_key"] == first["storage_key"]

    def test_upload_same_content_for_new_application_creates_evidence(
        self, session_factory, tmp_path
    ) -> None:
        """Identical content is reusable across applications."""
        actor = _make_actor()
        first_app_id = _create_app(session_factory, actor)
        second_app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)
        content = b"shared workbook content"

        first = svc.upload_evidence(
            stream=_make_stream(content),
            filename="questionnaire.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=first_app_id,
            intake_id=None,
            actor=actor,
        )
        second = svc.upload_evidence(
            stream=_make_stream(content),
            filename="questionnaire.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=second_app_id,
            intake_id=None,
            actor=actor,
        )

        assert second["deduplicated"] is False
        assert second["evidence_id"] != first["evidence_id"]
        assert second["storage_key"] == first["storage_key"]

    def test_upload_too_large_raises(
        self, session_factory, tmp_path
    ) -> None:
        """size_bytes > 50 MB → EvidenceTooLargeError raised before touching the store."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)

        # Spy: store root should remain empty because the check fires before IO.
        store_root = tmp_path / "evidence_store"
        svc = _make_service(session_factory, tmp_path)

        fifty_mb_plus_one = 50 * 1024 * 1024 + 1

        with pytest.raises(EvidenceTooLargeError):
            svc.upload_evidence(
                stream=_make_stream(b""),  # stream content irrelevant — check fires first
                filename="huge.xlsx",
                media_type=_XLSX_MEDIA_TYPE,
                size_bytes=fifty_mb_plus_one,
                application_id=app_id,
                intake_id=None,
                actor=actor,
            )

        # Verify the store root is empty (no temp files, no content blobs written)
        if store_root.exists():
            stored_files = list(store_root.rglob("*"))
            non_dir_files = [f for f in stored_files if f.is_file()]
            assert non_dir_files == [], (
                f"Store should be empty after EvidenceTooLargeError, found: {non_dir_files}"
            )

    def test_upload_disallowed_media_type_raises(
        self, session_factory, tmp_path
    ) -> None:
        """media_type='application/pdf' → EvidenceMediaTypeNotAllowedError."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)

        content = b"%PDF-1.4 fake pdf content"

        with pytest.raises(EvidenceMediaTypeNotAllowedError):
            svc.upload_evidence(
                stream=_make_stream(content),
                filename="document.pdf",
                media_type="application/pdf",
                size_bytes=len(content),
                application_id=app_id,
                intake_id=None,
                actor=actor,
            )

    def test_upload_allowed_octet_stream(
        self, session_factory, tmp_path
    ) -> None:
        """media_type='application/octet-stream' is an allowed type → succeeds."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)

        content = b"\x00\x01\x02\x03binary content"

        result = svc.upload_evidence(
            stream=_make_stream(content),
            filename="binary.bin",
            media_type=_OCTET_STREAM,
            size_bytes=len(content),
            application_id=app_id,
            intake_id=None,
            actor=actor,
        )

        assert "evidence_id" in result
        assert result["deduplicated"] is False

    def test_upload_allowed_xlsx_media_type(
        self, session_factory, tmp_path
    ) -> None:
        """XLSX media type is allowed → succeeds."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)

        content = b"PK\x03\x04xlsx content here"

        result = svc.upload_evidence(
            stream=_make_stream(content),
            filename="workbook.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=app_id,
            intake_id=None,
            actor=actor,
        )

        assert "evidence_id" in result
        assert result["deduplicated"] is False

    def test_upload_persists_evidence_item_to_db(
        self, session_factory, tmp_path
    ) -> None:
        """After upload, EvidenceRepository.get(evidence_id) returns a dict."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        svc = _make_service(session_factory, tmp_path)

        content = b"evidence bytes to persist"

        result = svc.upload_evidence(
            stream=_make_stream(content),
            filename="evidence.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            size_bytes=len(content),
            application_id=app_id,
            intake_id=None,
            actor=actor,
        )

        evidence_id = result["evidence_id"]

        # Verify via a fresh session
        session = session_factory()
        try:
            repo = EvidenceRepository(session)
            item = repo.get(evidence_id)
        finally:
            session.close()

        assert item is not None
        assert item["id"] == evidence_id
        assert item["application_id"] == app_id
        assert item["sha256_hex"] == result["sha256_hex"]
        assert item["state"] == "ACTIVE"


# ---------------------------------------------------------------------------
# GetEvidenceList tests
# ---------------------------------------------------------------------------


class TestGetEvidenceList:
    """GetEvidenceList query — E02 section 25.3."""

    def test_get_evidence_list_returns_active_items(
        self, session_factory, tmp_path
    ) -> None:
        """Upload 2 files for the same intake → list returns 2 ACTIVE items."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        intake_id = _create_intake(session_factory, actor, app_id)
        svc = _make_service(session_factory, tmp_path)

        # Upload two distinct files
        for i, content in enumerate([b"file one content", b"file two content"]):
            svc.upload_evidence(
                stream=_make_stream(content),
                filename=f"file{i}.xlsx",
                media_type=_XLSX_MEDIA_TYPE,
                size_bytes=len(content),
                application_id=app_id,
                intake_id=intake_id,
                actor=actor,
            )

        items = svc.get_evidence_list(intake_id)

        assert len(items) == 2
        for item in items:
            assert item["state"] == "ACTIVE"
            assert item["intake_id"] == intake_id

    def test_get_evidence_list_excludes_quarantined(
        self, session_factory, tmp_path
    ) -> None:
        """Upload 2 files, quarantine one → list returns only the 1 ACTIVE item."""
        actor = _make_actor()
        app_id = _create_app(session_factory, actor)
        intake_id = _create_intake(session_factory, actor, app_id)
        svc = _make_service(session_factory, tmp_path)

        # Upload two distinct files
        results = []
        for i, content in enumerate([b"keep this one ABCD", b"quarantine this XYZ"]):
            r = svc.upload_evidence(
                stream=_make_stream(content),
                filename=f"doc{i}.xlsx",
                media_type=_XLSX_MEDIA_TYPE,
                size_bytes=len(content),
                application_id=app_id,
                intake_id=intake_id,
                actor=actor,
            )
            results.append(r)

        # Quarantine the second item via the repository directly
        session = session_factory()
        try:
            repo = EvidenceRepository(session)
            repo.update_state(results[1]["evidence_id"], "QUARANTINED")
            session.commit()
        finally:
            session.close()

        items = svc.get_evidence_list(intake_id)

        assert len(items) == 1
        assert items[0]["state"] == "ACTIVE"
        assert items[0]["id"] == results[0]["evidence_id"]
