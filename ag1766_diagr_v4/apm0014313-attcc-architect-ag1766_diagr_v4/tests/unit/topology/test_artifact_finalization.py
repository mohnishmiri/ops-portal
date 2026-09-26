"""C7.2 artifact bundle finalization and integrity tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from types import MappingProxyType

import pytest
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.topology_finalization import (
    ArtifactFinalizationError,
    finalize_render_output,
)
from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake
from migration_intake.persistence.models_topology import (
    GenerationRun,
    TopologyBaseArtifact,
    TopologyInput,
)
from migration_intake.persistence.repositories.topology import TopologyRepository
from migration_intake.storage.filesystem import FilesystemStore


def seed_run(session: Session) -> tuple[str, str, str]:
    now = datetime.now(tz=UTC)
    actor_id, app_id, catalog_id, intake_id, base_id, run_id = (str(uuid.uuid4()) for _ in range(6))
    session.add(Actor(id=actor_id, display_name="Synthetic", created_at=now))
    session.add(
        Application(
            id=app_id,
            state="ACTIVE",
            display_name="Synthetic",
            created_at=now,
            updated_at=now,
            row_version=1,
            created_by_id=actor_id,
        )
    )
    session.add(
        CatalogRelease(
            id=catalog_id,
            semantic_version="1.0.0",
            source_filename="synthetic.csv",
            source_sha256="a" * 64,
            compiler_version="1.0.0",
            catalog_hash="b" * 64,
            pub_state="PUBLISHED",
            published_at=now,
            created_at=now,
        )
    )
    session.add(
        Intake(
            id=intake_id,
            application_id=app_id,
            catalog_id=catalog_id,
            state="FROZEN",
            created_at=now,
            updated_at=now,
            row_version=1,
            content_epoch=1,
            created_by_id=actor_id,
        )
    )
    session.flush()
    session.add(
        TopologyBaseArtifact(
            id=base_id,
            application_id=app_id,
            intake_id=intake_id,
            filename="base.xml",
            mime_type="application/xml",
            size_bytes=1,
            sha256_hex="c" * 64,
            content_address="cc/" + "c" * 64,
            uploaded_by_id=actor_id,
            uploaded_at=now,
            created_at=now,
            review_state="APPROVED",
            authority="OFFICIAL_SNAPSHOT",
            lifecycle="ACTIVE",
            profile_id="SYNTHETIC_LABEL_ONLY",
            profile_version="1.0.0",
            profile_hash="d" * 64,
            capability="LABEL_ONLY",
            selection_json={},
            selection_hash="e" * 64,
            compatibility_id=str(uuid.uuid4()),
        )
    )
    session.flush()
    input_id = str(uuid.uuid4())
    projection_json = (
        '{"application_id":"'
        + app_id
        + '","intake_id":"'
        + intake_id
        + '","schema_version":"1.0.0","snapshot_id":"snap","snapshot_hash":"'
        + ("a" * 64)
        + '","selection":{"application_id":"'
        + app_id
        + '","intake_id":"'
        + intake_id
        + (
            '","contexts":[{"environment":"PROD","site_id":"SITE_A"}],'
            '"view_variant":"combined-overview-with-details"},'
            '"partitions":[{"context":{"environment":"PROD","site_id":"SITE_A"},'
            '"facts":[],"resources":[]}],"shared_resources":[],'
            '"relationships":[],"issues":[]}'
        )
    )
    projection_hash = hashlib.sha256(projection_json.encode()).hexdigest()
    session.add(
        TopologyInput(
            id=input_id,
            application_id=app_id,
            intake_id=intake_id,
            mode="OFFICIAL_SNAPSHOT",
            snapshot_id=None,
            capture_id=None,
            projection_json=projection_json,
            projection_sha256=projection_hash,
            selection_json={
                "application_id": app_id,
                "intake_id": intake_id,
                "contexts": [{"environment": "PROD", "site_id": "SITE_A"}],
                "view_variant": "combined-overview-with-details",
            },
            selection_sha256="e" * 64,
            capability="LABEL_ONLY",
            base_artifact_id=base_id,
            base_sha256="c" * 64,
            compatibility_id=None,
            compatibility_key="1" * 64,
            compatibility_result_hash="2" * 64,
            profile_id="SYNTHETIC_LABEL_ONLY",
            profile_hash="d" * 64,
            catalog_sha256="b" * 64,
            generator_version="c7-test",
            parser_policy_hash="f" * 64,
            layout_policy_hash="0" * 64,
            result_policy_hash="1" * 64,
            semantic_input_hash="f" * 64,
            captured_by_id=actor_id,
            captured_at=now,
        )
    )
    session.add(
        GenerationRun(
            id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            base_artifact_id=base_id,
            base_sha256="c" * 64,
            input_id=input_id,
            mode="OFFICIAL_SNAPSHOT",
            capability="LABEL_ONLY",
            authority="OFFICIAL_SNAPSHOT",
            phase="STORING",
            row_version=2,
            semantic_input_hash="f" * 64,
            attempt_number=0,
            lease_token="lease-1",
            requested_by_id=actor_id,
            requested_at=now,
            created_at=now,
            status="STORING",
            approval_status="PENDING",
        )
    )
    session.commit()
    return run_id, actor_id, intake_id


class Output:
    diagram_bytes = b"<diagram>synthetic</diagram>"
    report_html = "<html>synthetic</html>"
    manifest = MappingProxyType({"result_status": "READY_FOR_REVIEW", "success": True})
    result_status = "READY_FOR_REVIEW"


class BadManifestOutput(Output):
    manifest = MappingProxyType({"result_status": "FAILED", "success": False})
    result_status = "FAILED"
    success = False


def test_finalization_stores_verifies_complete_bundle_and_completes_run(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")

    result = finalize_render_output(
        factory,
        storage,
        run_id=run_id,
        lease_token="lease-1",
        expected_row_version=2,
        output=Output(),
        actor_id=actor_id,
    )

    assert {item["artifact_type"] for item in result["artifacts"]} == {
        "DIAGRAM",
        "GAP_REPORT",
        "MANIFEST",
    }
    assert result["phase"] == "COMPLETED"
    assert result["readiness_json"]["artifact_types"] == [
        "DIAGRAM",
        "GAP_REPORT",
        "MANIFEST",
    ]
    for artifact in result["artifacts"]:
        with storage.retrieve(artifact["content_address"]) as stream:
            content = stream.read()
        assert len(content) == artifact["size_bytes"]
        assert hashlib.sha256(content).hexdigest() == artifact["sha256_hex"]
    manifest = next(item for item in result["artifacts"] if item["artifact_type"] == "MANIFEST")
    assert result["manifest_hash"] == manifest["sha256_hex"]


def test_finalization_rejects_stale_lease_without_partial_database_bundle(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactFinalizationError, match="lease"):
        finalize_render_output(
            factory,
            storage,
            run_id=run_id,
            lease_token="wrong",
            expected_row_version=2,
            output=Output(),
            actor_id=actor_id,
        )

    with factory() as session:
        assert TopologyRepository(session).list_artifacts_for_run(run_id) == []


def test_finalization_rejects_corrupt_deduplicated_object(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")

    original_store = storage.store

    def corrupting_store(stream, filename):
        receipt = original_store(stream, filename)
        path = (tmp_path / "artifacts" / receipt.storage_key).resolve()
        path.write_bytes(b"corrupted")
        return receipt

    storage.store = corrupting_store  # type: ignore[method-assign]
    with pytest.raises(ArtifactFinalizationError, match="read-back"):
        finalize_render_output(
            factory,
            storage,
            run_id=run_id,
            lease_token="lease-1",
            expected_row_version=2,
            output=Output(),
            actor_id=actor_id,
        )

    with factory() as session:
        assert TopologyRepository(session).list_artifacts_for_run(run_id) == []
        assert TopologyRepository(session).get_generation_run(run_id)["phase"] == "STORING"


def test_finalization_manifest_is_persisted_and_status_agrees(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")

    result = finalize_render_output(
        factory,
        storage,
        run_id=run_id,
        lease_token="lease-1",
        expected_row_version=2,
        output=BadManifestOutput(),
        actor_id=actor_id,
    )

    assert result["status"] == "FAILED"
    manifest = next(item for item in result["artifacts"] if item["artifact_type"] == "MANIFEST")
    assert result["manifest_hash"] == manifest["sha256_hex"]


def test_finalization_rejects_success_status_disagreement_without_bundle(
    tmp_engine, tmp_path
):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_run(session)
    output = Output()
    output.success = False
    with pytest.raises(ArtifactFinalizationError, match="success flag"):
        finalize_render_output(
            factory,
            FilesystemStore(tmp_path / "artifacts"),
            run_id=run_id,
            lease_token="lease-1",
            expected_row_version=2,
            output=output,
            actor_id=actor_id,
        )
    with factory() as session:
        assert TopologyRepository(session).list_artifacts_for_run(run_id) == []


def test_finalization_rolls_back_metadata_when_late_artifact_insert_fails(
    tmp_engine, tmp_path, monkeypatch
):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")
    original = TopologyRepository.create_generated_artifact
    calls = 0

    def fail_on_report(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic metadata failpoint")
        return original(self, **kwargs)

    monkeypatch.setattr(TopologyRepository, "create_generated_artifact", fail_on_report)
    with pytest.raises(ArtifactFinalizationError, match="Artifact finalization failed"):
        finalize_render_output(
            factory,
            storage,
            run_id=run_id,
            lease_token="lease-1",
            expected_row_version=2,
            output=Output(),
            actor_id=actor_id,
        )

    with factory() as session:
        repository = TopologyRepository(session)
        assert repository.list_artifacts_for_run(run_id) == []
        assert repository.get_generation_run(run_id)["phase"] == "FAILED"
