"""
Catalog release census and identity verification (P2A).

This module inventories packaged and published catalog releases by semantic
version, source hash, catalog hash, question count, and section count. It
detects identity collisions (same version with different hashes) and provides
decision-packet data for D-10 without exposing application values.

Architecture rules:
- Read-only analysis; never modifies releases or database state
- Compiles packaged artifacts to compute hashes deterministically
- Compares metadata only; does not select authoritative content
- Produces machine-readable census for coordinator review
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from migration_intake.catalog.compiler import CatalogCompiler
from migration_intake.persistence.unit_of_work import uow_context


@dataclass(frozen=True)
class PackagedCatalogInfo:
    """Metadata for a packaged catalog artifact."""

    filename: str
    semantic_version: str
    source_hash: str
    catalog_hash: str
    section_count: int
    question_count: int
    compiler_version: str
    file_path: Path


@dataclass(frozen=True)
class PublishedCatalogInfo:
    """Metadata for a published catalog release in the database."""

    release_id: str
    semantic_version: str
    source_hash: str
    catalog_hash: str | None
    section_count: int
    question_count: int
    compiler_version: str
    pub_state: str
    published_at: str | None


@dataclass(frozen=True)
class CatalogIdentityConflict:
    """Detected identity collision between catalog releases."""

    conflict_type: str  # "SAME_VERSION_DIFFERENT_SOURCE" | "SAME_VERSION_DIFFERENT_CATALOG"
    semantic_version: str
    source_a: str  # "packaged:{filename}" | "published:{release_id}"
    source_b: str
    hash_a: str
    hash_b: str
    detail: str


@dataclass(frozen=True)
class CatalogCensus:
    """Complete inventory of packaged and published catalog releases."""

    packaged_releases: tuple[PackagedCatalogInfo, ...]
    published_releases: tuple[PublishedCatalogInfo, ...]
    conflicts: tuple[CatalogIdentityConflict, ...]
    has_conflicts: bool


class CatalogCensusService:
    """
    Inventory and verify catalog release identity.

    This service compiles packaged artifacts, queries published releases,
    and detects identity collisions without modifying any state.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._compiler = CatalogCompiler()

    def generate_census(self, catalog_data_dir: Path) -> CatalogCensus:
        """
        Generate a complete census of packaged and published catalogs.

        Args:
            catalog_data_dir: Directory containing packaged catalog CSV files

        Returns:
            CatalogCensus with all releases and detected conflicts
        """
        packaged = self._inventory_packaged_catalogs(catalog_data_dir)
        published = self._inventory_published_catalogs()
        conflicts = self._detect_conflicts(packaged, published)

        return CatalogCensus(
            packaged_releases=tuple(packaged),
            published_releases=tuple(published),
            conflicts=tuple(conflicts),
            has_conflicts=len(conflicts) > 0,
        )

    def _inventory_packaged_catalogs(
        self, catalog_data_dir: Path
    ) -> list[PackagedCatalogInfo]:
        """Compile and inventory all packaged catalog CSV files."""
        packaged: list[PackagedCatalogInfo] = []

        for csv_file in sorted(catalog_data_dir.glob("catalog-*.csv")):
            try:
                content = csv_file.read_text(encoding="utf-8-sig")

                # Extract version from filename (e.g., "catalog-1.0.0.csv" -> "1.0.0")
                version = csv_file.stem.replace("catalog-", "")

                result = self._compiler.compile(
                    content,
                    version=version,
                    source_filename=csv_file.name,
                )

                if result.release is None:
                    # Compilation failed; skip this file
                    continue

                packaged.append(
                    PackagedCatalogInfo(
                        filename=csv_file.name,
                        semantic_version=result.release.version,
                        source_hash=result.release.source_hash,
                        catalog_hash=result.release.canonical_hash,
                        section_count=result.report.section_count,
                        question_count=result.report.question_count,
                        compiler_version=result.release.compiler_version,
                        file_path=csv_file,
                    )
                )
            except Exception:
                # Skip files that cannot be read or compiled
                continue

        return packaged

    def _inventory_published_catalogs(self) -> list[PublishedCatalogInfo]:
        """Query and inventory all published catalog releases from the database."""
        published: list[PublishedCatalogInfo] = []

        with uow_context(self._session_factory) as uow:
            releases = uow.catalogs.list_all_releases()

            for release in releases:
                # Count sections and questions for this release
                sections = uow.catalogs.get_sections_for_release(release["id"])
                question_count = sum(
                    len(uow.catalogs.get_questions_for_section(section["id"]))
                    for section in sections
                )

                published.append(
                    PublishedCatalogInfo(
                        release_id=release["id"],
                        semantic_version=release["semantic_version"],
                        source_hash=release["source_sha256"],
                        catalog_hash=release.get("catalog_hash"),
                        section_count=len(sections),
                        question_count=question_count,
                        compiler_version=release["compiler_version"],
                        pub_state=release["pub_state"],
                        published_at=release.get("published_at"),
                    )
                )

        return published

    def _detect_conflicts(
        self,
        packaged: list[PackagedCatalogInfo],
        published: list[PublishedCatalogInfo],
    ) -> list[CatalogIdentityConflict]:
        """Detect identity collisions between packaged and published releases."""
        conflicts: list[CatalogIdentityConflict] = []

        # Build version index
        by_version: dict[str, list[tuple[str, str, str, str]]] = {}
        # Each entry: (source_label, source_hash, catalog_hash, detail)

        for pkg in packaged:
            by_version.setdefault(pkg.semantic_version, []).append((
                f"packaged:{pkg.filename}",
                pkg.source_hash,
                pkg.catalog_hash,
                f"{pkg.question_count} questions, {pkg.section_count} sections",
            ))

        for pub in published:
            by_version.setdefault(pub.semantic_version, []).append((
                f"published:{pub.release_id}",
                pub.source_hash,
                pub.catalog_hash or "(null)",
                f"{pub.question_count} questions, {pub.section_count} sections, {pub.pub_state}",
            ))

        # Detect conflicts within each version
        for version, entries in by_version.items():
            if len(entries) < 2:
                continue

            # Check all pairs for conflicts
            for i, (source_a, hash_a, cat_a, detail_a) in enumerate(entries):
                for source_b, hash_b, cat_b, detail_b in entries[i + 1:]:
                    # Same version, different source hash
                    if hash_a != hash_b:
                        conflicts.append(
                            CatalogIdentityConflict(
                                conflict_type="SAME_VERSION_DIFFERENT_SOURCE",
                                semantic_version=version,
                                source_a=source_a,
                                source_b=source_b,
                                hash_a=hash_a,
                                hash_b=hash_b,
                                detail=f"{source_a}: {detail_a}; {source_b}: {detail_b}",
                            )
                        )
                    # Same version and source hash, but different catalog hash
                    elif cat_a != cat_b and cat_a != "(null)" and cat_b != "(null)":
                        conflicts.append(
                            CatalogIdentityConflict(
                                conflict_type="SAME_VERSION_DIFFERENT_CATALOG",
                                semantic_version=version,
                                source_a=source_a,
                                source_b=source_b,
                                hash_a=cat_a,
                                hash_b=cat_b,
                                detail=f"Source hashes match ({hash_a}) but catalog hashes differ",
                            )
                        )

        return conflicts

    def format_census_report(self, census: CatalogCensus) -> str:
        """Format census as human-readable report for D-10 decision packet."""
        lines = [
            "=" * 80,
            "CATALOG RELEASE CENSUS (P2A)",
            "=" * 80,
            "",
            f"Packaged Releases: {len(census.packaged_releases)}",
            f"Published Releases: {len(census.published_releases)}",
            f"Conflicts Detected: {len(census.conflicts)}",
            "",
        ]

        if census.packaged_releases:
            lines.extend([
                "-" * 80,
                "PACKAGED RELEASES",
                "-" * 80,
            ])
            for pkg in census.packaged_releases:
                lines.extend([
                    "",
                    f"File: {pkg.filename}",
                    f"  Version: {pkg.semantic_version}",
                    f"  Source Hash: {pkg.source_hash[:16]}...",
                    f"  Catalog Hash: {pkg.catalog_hash[:16]}...",
                    f"  Questions: {pkg.question_count}, Sections: {pkg.section_count}",
                    f"  Compiler: {pkg.compiler_version}",
                ])

        if census.published_releases:
            lines.extend([
                "",
                "-" * 80,
                "PUBLISHED RELEASES",
                "-" * 80,
            ])
            for pub in census.published_releases:
                lines.extend([
                    "",
                    f"Release ID: {pub.release_id}",
                    f"  Version: {pub.semantic_version}",
                    f"  Source Hash: {pub.source_hash[:16]}...",
                    f"  Catalog Hash: {pub.catalog_hash[:16] if pub.catalog_hash else '(null)'}...",
                    f"  Questions: {pub.question_count}, Sections: {pub.section_count}",
                    f"  State: {pub.pub_state}",
                    f"  Compiler: {pub.compiler_version}",
                ])

        if census.conflicts:
            lines.extend([
                "",
                "-" * 80,
                "CONFLICTS DETECTED",
                "-" * 80,
            ])
            for conflict in census.conflicts:
                lines.extend([
                    "",
                    f"Type: {conflict.conflict_type}",
                    f"  Version: {conflict.semantic_version}",
                    f"  Source A: {conflict.source_a}",
                    f"  Source B: {conflict.source_b}",
                    f"  Hash A: {conflict.hash_a[:16]}...",
                    f"  Hash B: {conflict.hash_b[:16]}...",
                    f"  Detail: {conflict.detail}",
                ])

        lines.extend([
            "",
            "=" * 80,
            "END CENSUS",
            "=" * 80,
        ])

        return "\n".join(lines)
