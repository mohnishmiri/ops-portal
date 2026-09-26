"""
Catalog admin CSV upload → validate → publish service — CAT-B3.

This is a thin, browser-facing wrapper around the exact same compile-then-
publish pipeline already used by ``catalog/bootstrap.py`` (CLI) and the
auto-bootstrap startup hook (CAT-A1): ``CatalogCompiler().compile(...)``
followed by ``CatalogPublicationService.publish_release(...)``.

Design rules applied here (carried over from ``catalog/bootstrap.py``):
- The compiler is the single source of validation truth. This module does
  not re-implement or bypass catalog validation.
- ``preview()`` never touches the database.
- ``publish()`` never trusts a client-held preview result — it re-runs the
  full compile step internally before persisting, because the browser could
  have tampered with a client-side preview, or another version could have
  been published in the interim.
- ``CatalogPublicationService`` and ``CatalogCompiler`` are reused unchanged;
  only a new caller is added here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from migration_intake.application.errors import ApplicationServiceError
from migration_intake.application.services.catalogs import CatalogPublicationService
from migration_intake.catalog.compiler import CatalogCompiler, CompileResult

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from migration_intake.application.dto import ActorContext
    from migration_intake.catalog.definitions import CatalogRelease


class CatalogCompileError(ApplicationServiceError):
    """
    Raised when an uploaded catalog CSV fails compilation.

    Carries the full diagnostics list (as plain dicts, matching
    ``CompilerReport.diagnostics.to_list()``) so the route layer can return
    them verbatim in a 400 response body.
    """

    def __init__(self, message: str, diagnostics: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def _sections_for_persistence(release: CatalogRelease) -> list[dict[str, Any]]:
    """
    Transform a compiled ``CatalogRelease`` into the section/question dict
    shape ``CatalogPublicationService.publish_release()`` expects.

    This is the same transform ``catalog/bootstrap.py``'s
    ``_sections_for_persistence()`` performs. It is duplicated here (rather
    than imported) because this packet's exclusive-files scope does not
    include ``catalog/bootstrap.py`` and the two callers must not share a
    module that neither packet owns.
    """
    questions_by_section: dict[str, list[dict[str, Any]]] = {}
    for question in release.questions.values():
        questions_by_section.setdefault(question.section_code, []).append(
            {
                "question_code": question.question_id,
                "question_text": question.question_text,
                "response_type": question.response_type,
                "required_level": question.required_level,
                "collection_mode": question.collection_mode,
                "display_order": question.order,
                "condition_ast": (
                    question.applicability_condition.compiled_ast
                    if question.applicability_condition
                    else None
                ),
                "response_schema_version": question.response_schema_version,
            }
        )

    return [
        {
            "section_code": section.code,
            "display_name": section.title,
            "display_order": section.order,
            "questions": sorted(
                questions_by_section.get(section.code, []),
                key=lambda question: question["display_order"],
            ),
        }
        for section in release.sections
    ]


class CatalogAdminPublishService:
    """Compile-then-publish workflow for admin-uploaded catalog CSVs."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._publication_service = CatalogPublicationService(session_factory)

    def preview(
        self, content: bytes, filename: str, semantic_version: str
    ) -> CompileResult:
        """
        Compile uploaded CSV bytes and return the full diagnostics report.

        Does NOT touch the database. Decodes content as ``utf-8-sig`` to
        match ``publish_catalog()``'s existing
        ``source.read_text(encoding="utf-8-sig")`` convention (tolerates a
        UTF-8 BOM from Excel-exported CSVs).
        """
        text = content.decode("utf-8-sig")
        return CatalogCompiler().compile(
            text,
            version=semantic_version,
            source_filename=filename,
        )

    def publish(
        self,
        content: bytes,
        filename: str,
        semantic_version: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        """
        Re-compile uploaded CSV bytes and publish the resulting release.

        Never trusts a client-held preview result as proof of validity —
        the compile step is re-run here from the raw bytes on every call.

        Raises:
            CatalogCompileError: Compilation failed; no release is created.
            CatalogVersionConflictError: ``semantic_version`` already exists
                with a different content hash (propagated unchanged from
                ``CatalogPublicationService.publish_release()``).
        """
        result = self.preview(content, filename, semantic_version)
        if result.release is None:
            diagnostics = result.report.diagnostics.to_list()
            summary = "; ".join(
                f"{item.code}: {item.message}" for item in result.report.diagnostics.all()
            )
            raise CatalogCompileError(
                f"Catalog compilation failed: {summary}", diagnostics
            )

        return self._publication_service.publish_release(
            semantic_version=result.release.version,
            source_filename=result.release.source_filename,
            source_sha256=result.release.source_hash,
            catalog_hash=result.release.canonical_hash,
            compiler_version=result.release.compiler_version,
            sections=_sections_for_persistence(result.release),
            compiler_report={
                "diagnostics": result.report.diagnostics.to_list(),
                "section_count": result.report.section_count,
                "question_count": result.report.question_count,
                "type_counts": result.report.type_counts,
                "published_by_actor_id": actor.actor_id,
            },
        )
