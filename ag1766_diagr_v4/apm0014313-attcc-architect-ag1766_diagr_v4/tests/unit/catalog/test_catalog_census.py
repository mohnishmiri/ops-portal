"""
Tests for catalog census and identity verification (P2A).

These tests verify that the census service correctly inventories packaged
and published catalog releases, computes hashes deterministically, and
detects identity collisions.
"""

from pathlib import Path
from datetime import datetime, timezone

import pytest

from migration_intake.catalog.census import (
    CatalogCensusService,
    CatalogIdentityConflict,
)
from migration_intake.application.services.catalogs import CatalogPublicationService
from migration_intake.catalog.compiler import CatalogCompiler


def test_census_inventories_packaged_catalogs(tmp_path: Path, session_factory):
    """Census correctly inventories packaged catalog CSV files."""
    # Create test catalog files
    catalog_dir = tmp_path / "catalogs"
    catalog_dir.mkdir()

    csv_content = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,What is the application name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER
APP-002,Application,What is the environment?,SINGLE_SELECT,DEV|TEST|PROD,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    (catalog_dir / "catalog-1.0.0.csv").write_text(csv_content, encoding="utf-8")
    (catalog_dir / "catalog-2.0.0.csv").write_text(csv_content, encoding="utf-8")

    census_service = CatalogCensusService(session_factory)
    census = census_service.generate_census(catalog_dir)

    assert len(census.packaged_releases) == 2
    assert census.packaged_releases[0].semantic_version in ("1.0.0", "2.0.0")
    assert census.packaged_releases[1].semantic_version in ("1.0.0", "2.0.0")
    assert census.packaged_releases[0].question_count == 2
    assert census.packaged_releases[0].section_count == 1


def test_census_computes_deterministic_hashes(tmp_path: Path, session_factory):
    """Census computes source and catalog hashes deterministically."""
    catalog_dir = tmp_path / "catalogs"
    catalog_dir.mkdir()

    csv_content = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,What is the application name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    (catalog_dir / "catalog-1.0.0.csv").write_text(csv_content, encoding="utf-8")

    census_service = CatalogCensusService(session_factory)
    census1 = census_service.generate_census(catalog_dir)
    census2 = census_service.generate_census(catalog_dir)

    assert len(census1.packaged_releases) == 1
    assert len(census2.packaged_releases) == 1
    
    pkg1 = census1.packaged_releases[0]
    pkg2 = census2.packaged_releases[0]
    
    assert pkg1.source_hash == pkg2.source_hash
    assert pkg1.catalog_hash == pkg2.catalog_hash
    assert len(pkg1.source_hash) == 64  # SHA-256 hex
    assert len(pkg1.catalog_hash) == 64


def test_census_detects_same_version_different_source_conflict(tmp_path: Path, session_factory):
    """Census detects when same version has different source hashes."""
    catalog_dir = tmp_path / "catalogs"
    catalog_dir.mkdir()

    csv_content_a = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,What is the application name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    csv_content_b = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,What is the application name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER
APP-002,Application,What is the environment?,SINGLE_SELECT,DEV|TEST|PROD,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    # Publish version 1.0.0 with content A
    (catalog_dir / "catalog-1.0.0.csv").write_text(csv_content_a, encoding="utf-8")
    compiler = CatalogCompiler()
    result_a = compiler.compile(csv_content_a, "1.0.0", "catalog-1.0.0.csv")
    
    pub_service = CatalogPublicationService(session_factory)
    pub_service.publish_release(
        semantic_version="1.0.0",
        source_filename="catalog-1.0.0.csv",
        source_sha256=result_a.release.source_hash,
        catalog_hash=result_a.release.canonical_hash,
        compiler_version="1.0.0",
        sections=[],
    )

    # Create packaged version 1.0.0 with content B (different)
    (catalog_dir / "catalog-1.0.0.csv").write_text(csv_content_b, encoding="utf-8")

    census_service = CatalogCensusService(session_factory)
    census = census_service.generate_census(catalog_dir)

    assert census.has_conflicts
    assert len(census.conflicts) >= 1
    
    conflict = next(
        c for c in census.conflicts
        if c.conflict_type == "SAME_VERSION_DIFFERENT_SOURCE"
    )
    assert conflict.semantic_version == "1.0.0"
    assert "packaged:" in conflict.source_a or "packaged:" in conflict.source_b
    assert "published:" in conflict.source_a or "published:" in conflict.source_b


def test_census_no_conflict_when_same_version_same_hash(tmp_path: Path, session_factory):
    """Census does not report conflict when version and hashes match."""
    catalog_dir = tmp_path / "catalogs"
    catalog_dir.mkdir()

    csv_content = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,What is the application name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    (catalog_dir / "catalog-1.0.0.csv").write_text(csv_content, encoding="utf-8")
    
    compiler = CatalogCompiler()
    result = compiler.compile(csv_content, "1.0.0", "catalog-1.0.0.csv")
    
    pub_service = CatalogPublicationService(session_factory)
    pub_service.publish_release(
        semantic_version="1.0.0",
        source_filename="catalog-1.0.0.csv",
        source_sha256=result.release.source_hash,
        catalog_hash=result.release.canonical_hash,
        compiler_version="1.0.0",
        sections=[],
    )

    census_service = CatalogCensusService(session_factory)
    census = census_service.generate_census(catalog_dir)

    assert not census.has_conflicts
    assert len(census.conflicts) == 0
    assert len(census.packaged_releases) == 1
    assert len(census.published_releases) == 1


def test_census_format_report_includes_all_sections(tmp_path: Path, session_factory):
    """Census report includes packaged, published, and conflicts sections."""
    catalog_dir = tmp_path / "catalogs"
    catalog_dir.mkdir()

    csv_content = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,What is the application name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    (catalog_dir / "catalog-1.0.0.csv").write_text(csv_content, encoding="utf-8")

    census_service = CatalogCensusService(session_factory)
    census = census_service.generate_census(catalog_dir)
    report = census_service.format_census_report(census)

    assert "CATALOG RELEASE CENSUS (P2A)" in report
    assert "PACKAGED RELEASES" in report
    assert "catalog-1.0.0.csv" in report
    assert "Version: 1.0.0" in report
    assert "Questions: 1" in report


def test_publication_rejects_same_version_different_source_hash(session_factory):
    """Publication service rejects same version with different source hash."""
    csv_content_a = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,Name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    csv_content_b = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,Name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER
APP-002,Application,Env?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    compiler = CatalogCompiler()
    result_a = compiler.compile(csv_content_a, "1.0.0", "catalog-a.csv")
    result_b = compiler.compile(csv_content_b, "1.0.0", "catalog-b.csv")

    pub_service = CatalogPublicationService(session_factory)
    
    # Publish first version
    pub_service.publish_release(
        semantic_version="1.0.0",
        source_filename="catalog-a.csv",
        source_sha256=result_a.release.source_hash,
        catalog_hash=result_a.release.canonical_hash,
        compiler_version="1.0.0",
        sections=[],
    )

    # Attempt to publish same version with different content
    from migration_intake.application.errors import CatalogVersionConflictError
    with pytest.raises(CatalogVersionConflictError) as exc_info:
        pub_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog-b.csv",
            source_sha256=result_b.release.source_hash,
            catalog_hash=result_b.release.canonical_hash,
            compiler_version="1.0.0",
            sections=[],
        )

    assert "different source hash" in str(exc_info.value)


def test_publication_idempotent_with_same_version_and_hash(session_factory):
    """Publication is idempotent when version and hash match."""
    csv_content = """Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination
APP-001,Application,Name?,TEXT,,REQUIRED,,WORKBOOK,,APPLICATION_OWNER,ALL,ANSWER"""

    compiler = CatalogCompiler()
    result = compiler.compile(csv_content, "1.0.0", "catalog.csv")

    pub_service = CatalogPublicationService(session_factory)
    
    # Publish first time
    release1 = pub_service.publish_release(
        semantic_version="1.0.0",
        source_filename="catalog.csv",
        source_sha256=result.release.source_hash,
        catalog_hash=result.release.canonical_hash,
        compiler_version="1.0.0",
        sections=[],
    )

    # Publish again with same content
    release2 = pub_service.publish_release(
        semantic_version="1.0.0",
        source_filename="catalog.csv",
        source_sha256=result.release.source_hash,
        catalog_hash=result.release.canonical_hash,
        compiler_version="1.0.0",
        sections=[],
    )

    assert release1["id"] == release2["id"]
    assert release1["source_sha256"] == release2["source_sha256"]
    assert release1["catalog_hash"] == release2["catalog_hash"]


# ============================================================================
# P2B Tests: Authoritative Release Manifest and Backfill
# ============================================================================


def test_bootstrap_constants_point_to_authoritative_release():
    """Bootstrap constants point to the D-10 authoritative release (1.0.0)."""
    from migration_intake.catalog.bootstrap import CATALOG_VERSION, CATALOG_FILENAME

    assert CATALOG_VERSION == "1.0.0"
    assert CATALOG_FILENAME == "catalog-1.0.0.csv"


def test_release_manifest_exists():
    """Release manifest file exists in catalog data directory."""
    from importlib.resources import files

    manifest_path = files("migration_intake.catalog.data").joinpath("RELEASE_MANIFEST.md")
    assert manifest_path.is_file()


def test_catalog_hash_backfill_updates_null_hashes(session_factory):
    """Backfill updates releases with null catalog_hash."""
    from migration_intake.persistence.unit_of_work import uow_context
    from datetime import datetime, timezone
    import uuid

    # Create a release with null catalog_hash (simulating PERF state)
    release_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    # Get the packaged catalog hash for comparison
    from migration_intake.catalog.bootstrap import packaged_catalog_path, CATALOG_VERSION
    from migration_intake.catalog.compiler import CatalogCompiler

    source = packaged_catalog_path()
    result = CatalogCompiler().compile(
        source.read_text(encoding="utf-8-sig"),
        version=CATALOG_VERSION,
        source_filename=source.name,
    )

    with uow_context(session_factory) as uow:
        # Insert release with matching source hash but null catalog_hash
        from migration_intake.persistence.models import CatalogRelease
        release = CatalogRelease(
            id=release_id,
            semantic_version="1.0.0",
            source_filename="catalog-1.0.0.csv",
            source_sha256=result.release.source_hash,
            catalog_hash=None,  # Null - needs backfill
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            published_at=now,
            created_at=now,
        )
        uow._session.add(release)
        uow.commit()

    # Run backfill
    from migration_intake.catalog.bootstrap import backfill_catalog_hashes
    updated = backfill_catalog_hashes(session_factory)

    assert updated == 1

    # Verify the hash was updated
    with uow_context(session_factory) as uow:
        updated_release = uow.catalogs.get_release(release_id)
        assert updated_release["catalog_hash"] == result.release.canonical_hash


def test_catalog_hash_backfill_skips_mismatched_source(session_factory):
    """Backfill skips releases with different source hash."""
    from migration_intake.persistence.unit_of_work import uow_context
    from datetime import datetime, timezone
    import uuid

    # Create a release with null catalog_hash but different source hash
    release_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    with uow_context(session_factory) as uow:
        from migration_intake.persistence.models import CatalogRelease
        release = CatalogRelease(
            id=release_id,
            semantic_version="0.9.0",
            source_filename="catalog-0.9.0.csv",
            source_sha256="d" * 64,  # Different source (valid 64-char hex)
            catalog_hash=None,  # Null - but source doesn't match
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            published_at=now,
            created_at=now,
        )
        uow._session.add(release)
        uow.commit()

    # Run backfill
    from migration_intake.catalog.bootstrap import backfill_catalog_hashes
    updated = backfill_catalog_hashes(session_factory)

    assert updated == 0  # Should not update mismatched source

    # Verify the hash is still null
    with uow_context(session_factory) as uow:
        unchanged_release = uow.catalogs.get_release(release_id)
        assert unchanged_release["catalog_hash"] is None


def test_repository_get_releases_with_null_catalog_hash(session_factory):
    """Repository correctly finds releases with null catalog_hash."""
    from migration_intake.persistence.unit_of_work import uow_context
    from datetime import datetime, timezone
    import uuid

    now = datetime.now(tz=timezone.utc)

    with uow_context(session_factory) as uow:
        from migration_intake.persistence.models import CatalogRelease

        # Release with null hash
        release1 = CatalogRelease(
            id=str(uuid.uuid4()),
            semantic_version="1.0.0",
            source_filename="catalog-1.0.0.csv",
            source_sha256="a" * 64,
            catalog_hash=None,
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            published_at=now,
            created_at=now,
        )
        uow._session.add(release1)

        # Release with hash
        release2 = CatalogRelease(
            id=str(uuid.uuid4()),
            semantic_version="2.0.0",
            source_filename="catalog-2.0.0.csv",
            source_sha256="b" * 64,
            catalog_hash="c" * 64,  # Has hash
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            published_at=now,
            created_at=now,
        )
        uow._session.add(release2)
        uow.commit()

    with uow_context(session_factory) as uow:
        null_hash_releases = uow.catalogs.get_releases_with_null_catalog_hash()

    assert len(null_hash_releases) == 1
    assert null_hash_releases[0]["semantic_version"] == "1.0.0"
