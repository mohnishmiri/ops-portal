"""
Canonical intake package export — X01.

Exports frozen intakes as canonical packages for downstream consumers
(Topology, ADS, DDD).

Package format:
- JSON manifest with metadata and hash
- Canonical JSON payload
- Optional attachments (evidence references, not raw bytes)

Export is idempotent: same snapshot produces same package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from migration_intake.application.snapshots import CanonicalSerializer
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.topology import TopologyRepository

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ExportManifest:
    """Manifest for an exported intake package."""

    format_version: str
    export_timestamp: str  # ISO 8601 UTC
    snapshot_id: str
    intake_id: str
    application_id: str
    catalog_id: str
    schema_version: str
    payload_sha256: str
    catalog_sha256: str
    topology_run_id: str | None = None
    topology_manifest_hash: str | None = None
    topology_approval_status: str | None = None


@dataclass
class ExportPackage:
    """A complete export package."""

    manifest: ExportManifest
    canonical_json: str
    manifest_json: str


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class ExportService:
    """
    Exports frozen intakes as canonical packages.

    Export is idempotent: same snapshot produces same package.
    """

    FORMAT_VERSION = "1.0.0"

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def export_intake(self, intake_id: str) -> ExportPackage | None:
        """
        Export a frozen intake as a canonical package.

        Returns None if intake has no snapshot (not frozen).
        """
        now = datetime.now(tz=UTC)

        with self._session_factory() as session:
            snapshot_repo = SnapshotRepository(session)
            snapshot = snapshot_repo.get_by_intake_id(intake_id)

            if snapshot is None:
                return None

            # Parse canonical JSON to extract metadata
            payload = json.loads(snapshot["canonical_json"])
            topology_run = TopologyRepository(session).get_approved_official_run_for_snapshot(
                application_id=payload.get("application", {}).get("id", ""),
                intake_id=intake_id,
                snapshot_id=snapshot["id"],
            )

            # Create manifest
            manifest = ExportManifest(
                format_version=self.FORMAT_VERSION,
                export_timestamp=CanonicalSerializer.normalize_timestamp(now),
                snapshot_id=snapshot["id"],
                intake_id=intake_id,
                application_id=payload.get("application", {}).get("id", ""),
                catalog_id=payload.get("catalog", {}).get("id", ""),
                schema_version=snapshot["schema_version"],
                payload_sha256=snapshot["sha256_hex"],
                catalog_sha256=snapshot["catalog_sha256"],
                topology_run_id=topology_run["id"] if topology_run else None,
                topology_manifest_hash=topology_run["manifest_hash"] if topology_run else None,
                topology_approval_status=topology_run["approval_status"] if topology_run else None,
            )

            # Serialize manifest
            manifest_dict = {
                "format_version": manifest.format_version,
                "export_timestamp": manifest.export_timestamp,
                "snapshot_id": manifest.snapshot_id,
                "intake_id": manifest.intake_id,
                "application_id": manifest.application_id,
                "catalog_id": manifest.catalog_id,
                "schema_version": manifest.schema_version,
                "payload_sha256": manifest.payload_sha256,
                "catalog_sha256": manifest.catalog_sha256,
                "topology_run_id": manifest.topology_run_id,
                "topology_manifest_hash": manifest.topology_manifest_hash,
                "topology_approval_status": manifest.topology_approval_status,
            }
            manifest_json = json.dumps(
                manifest_dict,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            return ExportPackage(
                manifest=manifest,
                canonical_json=snapshot["canonical_json"],
                manifest_json=manifest_json,
            )

    def export_by_snapshot_id(self, snapshot_id: str) -> ExportPackage | None:
        """
        Export by snapshot ID.

        Returns None if snapshot not found.
        """
        now = datetime.now(tz=UTC)

        with self._session_factory() as session:
            snapshot_repo = SnapshotRepository(session)
            snapshot = snapshot_repo.get_by_id(snapshot_id)

            if snapshot is None:
                return None

            # Parse canonical JSON to extract metadata
            payload = json.loads(snapshot["canonical_json"])
            topology_run = TopologyRepository(session).get_approved_official_run_for_snapshot(
                application_id=payload.get("application", {}).get("id", ""),
                intake_id=snapshot["intake_id"],
                snapshot_id=snapshot_id,
            )

            # Create manifest
            manifest = ExportManifest(
                format_version=self.FORMAT_VERSION,
                export_timestamp=CanonicalSerializer.normalize_timestamp(now),
                snapshot_id=snapshot_id,
                intake_id=snapshot["intake_id"],
                application_id=payload.get("application", {}).get("id", ""),
                catalog_id=payload.get("catalog", {}).get("id", ""),
                schema_version=snapshot["schema_version"],
                payload_sha256=snapshot["sha256_hex"],
                catalog_sha256=snapshot["catalog_sha256"],
                topology_run_id=topology_run["id"] if topology_run else None,
                topology_manifest_hash=topology_run["manifest_hash"] if topology_run else None,
                topology_approval_status=topology_run["approval_status"] if topology_run else None,
            )

            # Serialize manifest
            manifest_dict = {
                "format_version": manifest.format_version,
                "export_timestamp": manifest.export_timestamp,
                "snapshot_id": manifest.snapshot_id,
                "intake_id": manifest.intake_id,
                "application_id": manifest.application_id,
                "catalog_id": manifest.catalog_id,
                "schema_version": manifest.schema_version,
                "payload_sha256": manifest.payload_sha256,
                "catalog_sha256": manifest.catalog_sha256,
                "topology_run_id": manifest.topology_run_id,
                "topology_manifest_hash": manifest.topology_manifest_hash,
                "topology_approval_status": manifest.topology_approval_status,
            }
            manifest_json = json.dumps(
                manifest_dict,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            return ExportPackage(
                manifest=manifest,
                canonical_json=snapshot["canonical_json"],
                manifest_json=manifest_json,
            )

    def verify_package(self, package: ExportPackage) -> bool:
        """
        Verify that a package's payload matches its manifest hash.

        Returns True if valid, False otherwise.
        """
        return CanonicalSerializer.verify_hash(
            package.canonical_json,
            package.manifest.payload_sha256,
        )
