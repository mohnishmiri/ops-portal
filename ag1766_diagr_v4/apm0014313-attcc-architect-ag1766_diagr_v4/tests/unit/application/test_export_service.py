"""
Unit tests for ExportService — X01.

Verifies:
- Export creates package with manifest and payload
- Export is idempotent (same snapshot, same package)
- Package verification works
- Non-frozen intake returns None
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    Intake,
    Base,
)
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.application.services.export import ExportService
from migration_intake.application.services.snapshots import SnapshotService
from migration_intake.application.dto import ActorContext
from migration_intake.persistence.models_topology import GenerationRun


@pytest.fixture
def tmp_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(tmp_engine):
    """Create a session factory."""
    return sessionmaker(bind=tmp_engine)


@pytest.fixture
def export_service(session_factory) -> ExportService:
    """Create an ExportService instance."""
    return ExportService(session_factory)


@pytest.fixture
def snapshot_service(session_factory) -> SnapshotService:
    """Create a SnapshotService instance."""
    return SnapshotService(session_factory)


@pytest.fixture
def actor_context() -> ActorContext:
    """Create an actor context for testing."""
    return ActorContext(
        actor_id=str(uuid.uuid4()),
        display_name="Test Actor",
    )


def _seed_prerequisites(session_factory, actor_id: str) -> dict:
    """Seed prerequisite records."""
    now = datetime.now(tz=timezone.utc)

    with session_factory() as session:
        # Actor
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))

        # Application
        app_id = str(uuid.uuid4())
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Test App",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )

        # Catalog
        catalog_id = str(uuid.uuid4())
        session.add(
            CatalogRelease(
                id=catalog_id,
                semantic_version="1.0.0",
                source_filename="catalog.yaml",
                source_sha256="a" * 64,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                published_at=now,
                created_at=now,
            )
        )

        # Intake
        intake_id = str(uuid.uuid4())
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=catalog_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )

        session.commit()

        return {
            "actor_id": actor_id,
            "app_id": app_id,
            "catalog_id": catalog_id,
            "intake_id": intake_id,
        }


class TestExportIntake:
    """Tests for export_intake."""

    def test_exports_frozen_intake(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        """Exports a frozen intake as a package."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        # Freeze the intake
        snapshot_service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        # Export
        package = export_service.export_intake(prereqs["intake_id"])

        assert package is not None
        assert package.manifest.intake_id == prereqs["intake_id"]
        assert package.canonical_json is not None
        assert package.manifest_json is not None

    def test_returns_none_for_non_frozen(
        self,
        session_factory,
        export_service: ExportService,
        actor_context: ActorContext,
    ) -> None:
        """Returns None for non-frozen intake."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        package = export_service.export_intake(prereqs["intake_id"])

        assert package is None

    def test_manifest_contains_metadata(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        """Manifest contains required metadata."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        snapshot_service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        package = export_service.export_intake(prereqs["intake_id"])

        assert package is not None
        assert package.manifest.format_version == "1.0.0"
        assert package.manifest.snapshot_id is not None
        assert package.manifest.payload_sha256 is not None
        assert package.manifest.schema_version is not None


class TestExportIdempotency:
    """Tests for export idempotency."""

    def test_same_snapshot_same_payload(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        """Same snapshot produces same payload."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        snapshot_service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        package1 = export_service.export_intake(prereqs["intake_id"])
        package2 = export_service.export_intake(prereqs["intake_id"])

        assert package1 is not None
        assert package2 is not None
        assert package1.canonical_json == package2.canonical_json
        assert package1.manifest.payload_sha256 == package2.manifest.payload_sha256


class TestPackageVerification:
    """Tests for package verification."""

    def test_valid_package_verifies(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        """Valid package passes verification."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        snapshot_service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        package = export_service.export_intake(prereqs["intake_id"])

        assert package is not None
        assert export_service.verify_package(package) is True

    def test_tampered_package_fails_verification(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        """Tampered package fails verification."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        snapshot_service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        package = export_service.export_intake(prereqs["intake_id"])

        assert package is not None

        # Tamper with the payload
        tampered_json = package.canonical_json.replace("FROZEN", "TAMPERED")
        from migration_intake.application.services.export import ExportPackage
        tampered_package = ExportPackage(
            manifest=package.manifest,
            canonical_json=tampered_json,
            manifest_json=package.manifest_json,
        )

        assert export_service.verify_package(tampered_package) is False


class TestExportBySnapshotId:
    """Tests for export_by_snapshot_id."""

    def test_exports_by_snapshot_id(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        """Exports by snapshot ID."""
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)

        freeze_result = snapshot_service.freeze_intake(
            prereqs["intake_id"],
            actor_context,
            skip_readiness_check=True,
        )

        package = export_service.export_by_snapshot_id(freeze_result.snapshot_id)

        assert package is not None
        assert package.manifest.snapshot_id == freeze_result.snapshot_id

    def test_returns_none_for_unknown_snapshot(
        self,
        session_factory,
        export_service: ExportService,
    ) -> None:
        """Returns None for unknown snapshot ID."""
        package = export_service.export_by_snapshot_id(str(uuid.uuid4()))

        assert package is None


class TestApprovedTopologyLineage:
    """Exports bind downstream consumers to an exact approved run."""

    def test_includes_matching_approved_official_run(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)
        snapshot = snapshot_service.freeze_intake(
            prereqs["intake_id"], actor_context, skip_readiness_check=True
        )
        run_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)
        with session_factory() as session:
            session.add(
                GenerationRun(
                    id=run_id,
                    application_id=prereqs["app_id"],
                    intake_id=prereqs["intake_id"],
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_sha256="a" * 64,
                    catalog_sha256="b" * 64,
                    base_artifact_id=str(uuid.uuid4()),
                    base_sha256="c" * 64,
                    input_id=str(uuid.uuid4()),
                    mode="OFFICIAL_SNAPSHOT",
                    capability="LABEL_ONLY",
                    authority="OFFICIAL_SNAPSHOT",
                    phase="COMPLETED",
                    semantic_input_hash="d" * 64,
                    manifest_hash="e" * 64,
                    status="READY_FOR_REVIEW",
                    approval_status="APPROVED",
                    approved_by_id=actor_context.actor_id,
                    approved_at=now,
                    requested_by_id=actor_context.actor_id,
                    requested_at=now,
                    completed_at=now,
                    created_at=now,
                )
            )
            session.commit()

        package = export_service.export_by_snapshot_id(snapshot.snapshot_id)

        assert package is not None
        assert package.manifest.topology_run_id == run_id
        assert package.manifest.topology_manifest_hash == "e" * 64
        assert package.manifest.topology_approval_status == "APPROVED"
        manifest = json.loads(package.manifest_json)
        assert manifest["topology_run_id"] == run_id

    def test_omits_superseded_run(
        self,
        session_factory,
        export_service: ExportService,
        snapshot_service: SnapshotService,
        actor_context: ActorContext,
    ) -> None:
        prereqs = _seed_prerequisites(session_factory, actor_context.actor_id)
        snapshot = snapshot_service.freeze_intake(
            prereqs["intake_id"], actor_context, skip_readiness_check=True
        )
        now = datetime.now(tz=timezone.utc)
        with session_factory() as session:
            session.add(
                GenerationRun(
                    id=str(uuid.uuid4()),
                    application_id=prereqs["app_id"],
                    intake_id=prereqs["intake_id"],
                    snapshot_id=snapshot.snapshot_id,
                    base_artifact_id=str(uuid.uuid4()),
                    base_sha256="c" * 64,
                    mode="OFFICIAL_SNAPSHOT",
                    authority="OFFICIAL_SNAPSHOT",
                    phase="COMPLETED",
                    manifest_hash="e" * 64,
                    status="READY_FOR_REVIEW",
                    approval_status="APPROVED",
                    superseded_by_id=str(uuid.uuid4()),
                    requested_by_id=actor_context.actor_id,
                    requested_at=now,
                    completed_at=now,
                    created_at=now,
                )
            )
            session.commit()

        package = export_service.export_by_snapshot_id(snapshot.snapshot_id)

        assert package is not None
        assert package.manifest.topology_run_id is None
