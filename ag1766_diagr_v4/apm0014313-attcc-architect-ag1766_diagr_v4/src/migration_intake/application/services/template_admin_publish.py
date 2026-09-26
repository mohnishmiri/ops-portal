"""Template admin upload/preview/publish application service."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from migration_intake.application.errors import ApplicationServiceError
from migration_intake.persistence.repositories.templates import TemplateRepository
from migration_intake.persistence.unit_of_work import uow_context
from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.topology.template_compiler import TemplateCompileResult, TemplateCompiler

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from migration_intake.application.dto import ActorContext


class TemplateCompileError(ApplicationServiceError):
    """Raised when an uploaded template fails compile validation."""

    def __init__(self, message: str, diagnostics: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class TemplateVersionConflictError(ApplicationServiceError):
    """Raised when a version exists with different template bytes."""


class TemplateAdminPublishService:
    """Compile-then-publish workflow for topology template releases."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage_root: Path | str | None = None,
    ) -> None:
        self._session_factory = session_factory
        root = Path(storage_root) if storage_root is not None else Path("evidence")
        self._storage = FilesystemStore(root / "topology" / "templates")
        self._compiler = TemplateCompiler()

    def preview(self, content: bytes, filename: str) -> TemplateCompileResult:
        """Compile uploaded template bytes without any persistence writes."""
        return self._compiler.compile(content, filename=filename)

    def publish(
        self,
        content: bytes,
        filename: str,
        *,
        template_version: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        """Validate, store, and publish a topology template release."""
        result = self.preview(content, filename)
        if not result.is_valid:
            raise TemplateCompileError("Template compilation failed", result.diagnostics)

        now = datetime.now(tz=UTC)
        source_sha256 = result.source_sha256

        with uow_context(self._session_factory) as uow:
            repo = TemplateRepository(uow._session)
            same = repo.get_release_by_version_and_hash(template_version, source_sha256)
            if same is not None:
                return same

            existing_version = repo.get_release_by_version(template_version)
            if existing_version is not None:
                raise TemplateVersionConflictError(
                    f"Template version {template_version} already exists with different content"
                )

            receipt = self._storage.store(io.BytesIO(content), filename)
            release = repo.add_release(
                release_id=str(uuid.uuid4()),
                template_version=template_version,
                source_filename=filename,
                source_sha256=receipt.sha256_hex,
                content_address=receipt.storage_key,
                size_bytes=receipt.size_bytes,
                tab_count=result.tab_count,
                variant_manifest=result.variant_manifest,
                compiler_version=self._compiler.COMPILER_VERSION,
                compiler_report={"diagnostics": result.diagnostics},
                pub_state="PUBLISHED",
                published_at=now,
                published_by_id=actor.actor_id,
                created_at=now,
            )
            uow.commit()
            return release

    def activate(self, release_id: str, *, actor: ActorContext) -> dict[str, Any]:
        """Make a release active by publishing it at current timestamp."""
        now = datetime.now(tz=UTC)
        with uow_context(self._session_factory) as uow:
            repo = TemplateRepository(uow._session)
            row = repo.get_release(release_id)
            if row is None:
                raise TemplateVersionConflictError("Template release not found")
            if row["pub_state"] == "RETIRED":
                raise TemplateVersionConflictError("Retired template cannot be activated")
            updated = repo.update_pub_state(
                release_id,
                pub_state="PUBLISHED",
                published_at=now,
                published_by_id=actor.actor_id,
            )
            uow.commit()
            return updated

    def retire(self, release_id: str, *, actor: ActorContext) -> dict[str, Any]:
        """Retire a published release."""
        _ = actor  # retained for parity/audit expansion.
        now = datetime.now(tz=UTC)
        with uow_context(self._session_factory) as uow:
            repo = TemplateRepository(uow._session)
            row = repo.get_release(release_id)
            if row is None:
                raise TemplateVersionConflictError("Template release not found")
            updated = repo.update_pub_state(release_id, pub_state="RETIRED", retired_at=now)
            uow.commit()
            return updated
