"""Compile and publish the packaged, approved questionnaire catalog."""

from __future__ import annotations

import argparse
import uuid
from importlib.resources import files
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.services.catalog_maintenance import (
    CatalogMaintenanceService,
)
from migration_intake.application.services.catalogs import CatalogPublicationService
from migration_intake.catalog.compiler import CatalogCompiler
from migration_intake.catalog.definitions import CatalogRelease
from migration_intake.config import Settings
from migration_intake.observability.logging import StructuredLogger
from migration_intake.persistence.database import create_engine_from_url, create_session_factory
from migration_intake.persistence.unit_of_work import uow_context

CATALOG_VERSION = "1.0.0"
CATALOG_FILENAME = "catalog-1.0.0.csv"

#: Stable event code for auto-bootstrap failures (CAT-A1). Defined locally
#: because this packet's exclusive-files scope does not include
#: observability/logging.py, where EventCode constants otherwise live.
CATALOG_AUTOBOOTSTRAP_FAILED = "CATALOG_AUTOBOOTSTRAP_FAILED"


def packaged_catalog_path() -> Path:
    """Return the installed, versioned catalog artifact path."""
    return Path(str(files("migration_intake.catalog.data").joinpath(CATALOG_FILENAME)))


def _sections_for_persistence(release: CatalogRelease) -> list[dict[str, Any]]:
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
                "allowed_values": [
                    {"code": value.code, "label": value.label}
                    for value in question.allowed_values
                ],
                "response_schema_version": question.response_schema_version,
                "options": [
                    {"code": allowed.code, "label": allowed.label}
                    for allowed in question.allowed_values
                ],
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


def publish_catalog(session_factory: sessionmaker, source: Path) -> dict[str, Any]:
    """Compile a reviewed source artifact and idempotently publish its release."""
    content = source.read_text(encoding="utf-8-sig")
    result = CatalogCompiler().compile(
        content,
        version=CATALOG_VERSION,
        source_filename=source.name,
    )
    if result.release is None:
        diagnostics = "; ".join(
            f"{item.code}: {item.message}" for item in result.report.diagnostics.all()
        )
        raise ValueError(f"Catalog compilation failed: {diagnostics}")

    return CatalogPublicationService(session_factory).publish_release(
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
        },
    )


def backfill_catalog_hashes(session_factory: sessionmaker) -> int:
    """
    Backfill catalog_hash for releases that have null values.

    This handles PERF releases published before P2A collision guards were
    implemented. For each release with catalog_hash = null, we recompile
    from the packaged artifact (if source hashes match) and update the hash.

    Returns:
        The number of releases updated.
    """
    source = packaged_catalog_path()
    result = CatalogCompiler().compile(
        source.read_text(encoding="utf-8-sig"),
        version=CATALOG_VERSION,
        source_filename=source.name,
    )
    if result.release is None:
        return 0

    updated = 0
    with uow_context(session_factory) as uow:
        null_hash_releases = uow.catalogs.get_releases_with_null_catalog_hash()

        for release in null_hash_releases:
            # Only backfill if source hash matches the packaged artifact
            if release["source_sha256"] == result.release.source_hash:
                uow.catalogs.update_catalog_hash(
                    release["id"],
                    result.release.canonical_hash,
                )
                updated += 1

        if updated > 0:
            uow.commit()

    return updated


def repair_catalog_options(session_factory: sessionmaker) -> int:
    """
    Backfill allowed values for an already-published option-less release.

    Publication originally dropped the compiled ``allowed_values``, so
    releases published before that was fixed carry zero rows in
    ``cat_options`` and render empty ``<select>`` editors. Because releases
    are immutable and publication is idempotent on ``(version, hash)``,
    republishing the same artifact cannot add the missing rows — so this
    completes the incomplete publication in place instead.

    It only ever touches a release whose stored ``source_sha256`` equals the
    hash of the packaged artifact compiled here, so options can never be
    grafted onto a release that came from different source bytes. It is a
    no-op once any option exists for that release.

    Returns:
        The number of option rows written.
    """
    source = packaged_catalog_path()
    result = CatalogCompiler().compile(
        source.read_text(encoding="utf-8-sig"),
        version=CATALOG_VERSION,
        source_filename=source.name,
    )
    if result.release is None:
        return 0

    with uow_context(session_factory) as uow:
        release = uow.catalogs.get_release_by_version_and_hash(
            result.release.version, result.release.source_hash
        )
        if release is None or uow.catalogs.count_options_for_release(release["id"]) > 0:
            return 0

        allowed_by_code = {
            question.question_id: question.allowed_values
            for question in result.release.questions.values()
        }
        written = 0
        for section in uow.catalogs.get_sections_for_release(release["id"]):
            for question in uow.catalogs.get_questions_for_section(section["id"]):
                for order, allowed in enumerate(
                    allowed_by_code.get(question["question_code"], ()), start=1
                ):
                    uow.catalogs.add_option(
                        option_id=str(uuid.uuid4()),
                        question_id=question["id"],
                        option_code=allowed.code,
                        display_label=allowed.label or allowed.code,
                        display_order=order,
                    )
                    written += 1
        uow.commit()
        return written


def ensure_catalog_published(session_factory: sessionmaker) -> None:
    """Check catalog availability without mutating catalog rows at startup.

    Publication, hash repair, option repair, and intake repinning are explicit
    administrative operations. Startup only observes whether a published
    release exists; ``/health/ready`` remains responsible for reporting an
    unavailable catalog.

    Args:
        session_factory: SQLAlchemy session factory for the configured
            database.
    """
    try:
        if CatalogPublicationService(session_factory).get_latest_published() is None:
            StructuredLogger(__name__).warning(
                "No published catalog available at startup",
                event_code="CATALOG_NOT_PUBLISHED",
                operation="ensure_catalog_published",
                outcome="not_ready",
            )
    except Exception as exc:  # startup must never crash on this
        StructuredLogger(__name__).error(
            event_code=CATALOG_AUTOBOOTSTRAP_FAILED,
            operation="ensure_catalog_published",
            outcome="failed",
            exception_class=type(exc).__name__,
        )


def main() -> None:
    """Publish the catalog to the configured database."""
    parser = argparse.ArgumentParser(description="Compile and publish the packaged catalog")
    parser.add_argument("--source", type=Path, default=packaged_catalog_path())
    args = parser.parse_args()

    settings = Settings()
    engine = create_engine_from_url(settings.effective_database_url)
    session_factory = create_session_factory(engine)
    release = publish_catalog(session_factory, args.source)
    print(
        f"Catalog {release['semantic_version']} is {release['pub_state'].lower()} "
        f"(release {release['id']})."
    )


def maintenance_main() -> None:
    """Run explicit catalog repair or empty-draft repinning maintenance."""
    parser = argparse.ArgumentParser(description="Run explicit catalog maintenance")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the operation; without this flag the command is a dry run",
    )
    parser.add_argument(
        "--repair-packaged-release",
        action="store_true",
        help="Repair matching packaged-release hashes and missing options",
    )
    parser.add_argument("--repin-intake")
    parser.add_argument("--new-catalog-id")
    parser.add_argument("--expected-row-version", type=int)
    args = parser.parse_args()

    if args.repair_packaged_release == bool(args.repin_intake):
        parser.error("choose exactly one maintenance operation")
    if args.repin_intake and (
        args.new_catalog_id is None or args.expected_row_version is None
    ):
        parser.error(
            "--repin-intake requires --new-catalog-id and --expected-row-version"
        )

    settings = Settings()
    engine = create_engine_from_url(settings.effective_database_url)
    session_factory = create_session_factory(engine)
    actor = ActorContext(
        actor_id=str(settings.actor_id),
        display_name=settings.actor_display_name,
        role_codes=frozenset({"CATALOG_MANAGE"}),
    )
    service = CatalogMaintenanceService(session_factory)
    try:
        if args.repair_packaged_release:
            result = service.repair_packaged_release(actor=actor, apply=args.apply)
            print(
                f"Catalog maintenance dry_run={result.dry_run} "
                f"catalog_hashes_updated={result.catalog_hashes_updated} "
                f"options_repaired={result.options_repaired}"
            )
        else:
            result = service.repin_empty_draft(
                intake_id=args.repin_intake,
                new_catalog_id=args.new_catalog_id,
                expected_row_version=args.expected_row_version,
                actor=actor,
                apply=args.apply,
            )
            print(
                f"Catalog repin dry_run={result.dry_run} intake={result.intake_id} "
                f"old_catalog={result.old_catalog_id} new_catalog={result.new_catalog_id} "
                f"new_row_version={result.new_row_version}"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
