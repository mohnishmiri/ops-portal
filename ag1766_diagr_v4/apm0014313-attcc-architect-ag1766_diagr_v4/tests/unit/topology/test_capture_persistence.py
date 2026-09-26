"""C6.1 topology capture, reservation, run, review, and artifact contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake
from migration_intake.persistence.models_topology import TopologyBaseArtifact
from migration_intake.persistence.repositories.topology import (
    DuplicateArtifactError,
    GenerationConflictError,
    TopologyRepository,
)
from migration_intake.topology.contracts import GenerationMode, RenderCapability, RunPhase


def seed(session: Session) -> tuple[str, str, str, str]:
    now = datetime.now(tz=UTC)
    actor_id = str(uuid.uuid4())
    application_id = str(uuid.uuid4())
    catalog_id = str(uuid.uuid4())
    intake_id = str(uuid.uuid4())
    base_id = str(uuid.uuid4())
    session.add(Actor(id=actor_id, display_name="Synthetic actor", created_at=now))
    session.add(Application(id=application_id, state="ACTIVE", display_name="Synthetic", created_at=now, updated_at=now, row_version=1, created_by_id=actor_id))
    session.add(CatalogRelease(id=catalog_id, semantic_version="1.0.0", source_filename="synthetic.csv", source_sha256="a" * 64, compiler_version="1.0.0", pub_state="PUBLISHED", published_at=now, created_at=now))
    session.add(Intake(id=intake_id, application_id=application_id, catalog_id=catalog_id, state="FROZEN", created_at=now, updated_at=now, row_version=1, created_by_id=actor_id))
    session.flush()
    session.add(TopologyBaseArtifact(id=base_id, application_id=application_id, intake_id=intake_id, filename="base.drawio", mime_type="application/xml", size_bytes=10, sha256_hex="b" * 64, content_address="bb/" + "b" * 64, uploaded_by_id=actor_id, uploaded_at=now, created_at=now))
    session.commit()
    return actor_id, application_id, intake_id, base_id


def test_legacy_base_is_explicitly_unpinned(tmp_engine):
    with sessionmaker(bind=tmp_engine)() as session:
        _, _, intake_id, base_id = seed(session)
        repository = TopologyRepository(session)
        base = repository.get_base_artifact(base_id)

    assert base is not None
    assert base["authority"] == "LEGACY_UNPINNED"
    assert base["row_version"] == 1
    assert base["lifecycle"] == "HISTORICAL"
    assert base["intake_id"] == intake_id


def test_capture_input_and_reservation_pin_complete_identity(tmp_engine):
    with sessionmaker(bind=tmp_engine)() as session:
        actor_id, application_id, intake_id, base_id = seed(session)
        repository = TopologyRepository(session)
        now = datetime(2026, 9, 19, tzinfo=UTC)
        projection = '{"application":{"name":"Synthetic"}}'
        projection_hash = hashlib.sha256(projection.encode()).hexdigest()
        capture = repository.create_topology_capture(
            capture_id=str(uuid.uuid4()), intake_id=intake_id, content_epoch=1,
            schema_version="3.0.0", canonical_json=projection,
            sha256_hex=projection_hash, captured_by_id=actor_id, captured_at=now,
        )
        topology_input = repository.create_topology_input(
            input_id=str(uuid.uuid4()), application_id=application_id, intake_id=intake_id,
            mode=GenerationMode.DRAFT_PREVIEW.value, snapshot_id=None,
            capture_id=capture["id"], projection_json=projection,
            projection_sha256=projection_hash, selection_json='{"contexts":[]}',
            selection_sha256="1" * 64, capability=RenderCapability.LABEL_ONLY.value,
            base_artifact_id=base_id, base_sha256="b" * 64,
            profile_id="SYNTHETIC_LABEL_ONLY", profile_hash="c" * 64,
            catalog_sha256="d" * 64, generator_version="test-1",
            parser_policy_hash="e" * 64, layout_policy_hash="f" * 64,
            result_policy_hash="0" * 64, semantic_input_hash="1" * 64,
            captured_by_id=actor_id, captured_at=now,
        )
        run = repository.reserve_generation_run(
            run_id=str(uuid.uuid4()), input_id=topology_input["id"],
            application_id=application_id, intake_id=intake_id,
            semantic_input_hash="1" * 64, requested_by_id=actor_id,
            requested_at=now,
        )
        session.commit()

    assert capture["sha256_hex"] == projection_hash
    assert topology_input["mode"] == GenerationMode.DRAFT_PREVIEW.value
    assert topology_input["capability"] == RenderCapability.LABEL_ONLY.value
    assert run["phase"] == RunPhase.PENDING.value
    assert run["row_version"] == 1
    assert run["authority"] == "DRAFT_PREVIEW"


def test_duplicate_reservation_returns_original_run(tmp_engine):
    with sessionmaker(bind=tmp_engine)() as session:
        actor_id, application_id, intake_id, base_id = seed(session)
        repository = TopologyRepository(session)
        now = datetime.now(tz=UTC)
        input_id = str(uuid.uuid4())
        repository.create_topology_input(
            input_id=input_id, application_id=application_id, intake_id=intake_id,
            mode="DRAFT_PREVIEW", snapshot_id=None, capture_id=None,
            projection_json="{}", projection_sha256="a" * 64,
            selection_json="{}", selection_sha256="b" * 64, capability="LABEL_ONLY",
            base_artifact_id=base_id, base_sha256="c" * 64,
            profile_id="profile", profile_hash="d" * 64, catalog_sha256="e" * 64,
            generator_version="test", parser_policy_hash="f" * 64,
            layout_policy_hash="0" * 64, result_policy_hash="1" * 64,
            semantic_input_hash="2" * 64, captured_by_id=actor_id, captured_at=now,
        )
        first = repository.reserve_generation_run(
            run_id=str(uuid.uuid4()), input_id=input_id, application_id=application_id,
            intake_id=intake_id, semantic_input_hash="2" * 64,
            requested_by_id=actor_id, requested_at=now,
        )
        second = repository.reserve_generation_run(
            run_id=str(uuid.uuid4()), input_id=input_id, application_id=application_id,
            intake_id=intake_id, semantic_input_hash="2" * 64,
            requested_by_id=actor_id, requested_at=now,
        )

    assert second["id"] == first["id"]


def test_phase_transition_uses_row_version_cas(tmp_engine):
    with sessionmaker(bind=tmp_engine)() as session:
        actor_id, application_id, intake_id, base_id = seed(session)
        repository = TopologyRepository(session)
        now = datetime.now(tz=UTC)
        input_record = repository.create_topology_input(
            input_id=str(uuid.uuid4()), application_id=application_id, intake_id=intake_id,
            mode="DRAFT_PREVIEW", snapshot_id=None, capture_id=None,
            projection_json="{}", projection_sha256="a" * 64, selection_json="{}",
            selection_sha256="b" * 64, capability="LABEL_ONLY", base_artifact_id=base_id,
            base_sha256="c" * 64, profile_id="profile", profile_hash="d" * 64,
            catalog_sha256="e" * 64, generator_version="test", parser_policy_hash="f" * 64,
            layout_policy_hash="0" * 64, result_policy_hash="1" * 64,
            semantic_input_hash="2" * 64, captured_by_id=actor_id, captured_at=now,
        )
        run = repository.reserve_generation_run(
            run_id=str(uuid.uuid4()), input_id=input_record["id"], application_id=application_id,
            intake_id=intake_id, semantic_input_hash="2" * 64,
            requested_by_id=actor_id, requested_at=now,
        )
        transitioned = repository.transition_generation_phase(
            run_id=run["id"], expected_row_version=1,
            expected_phase=RunPhase.PENDING.value, new_phase=RunPhase.CAPTURING.value,
        )
        with pytest.raises(GenerationConflictError):
            repository.transition_generation_phase(
                run_id=run["id"], expected_row_version=1,
                expected_phase=RunPhase.PENDING.value, new_phase=RunPhase.RENDERING.value,
            )

    assert transitioned["phase"] == RunPhase.CAPTURING.value
    assert transitioned["row_version"] == 2


def test_artifact_type_is_unique_per_run(tmp_engine):
    with sessionmaker(bind=tmp_engine)() as session:
        actor_id, application_id, intake_id, base_id = seed(session)
        repository = TopologyRepository(session)
        now = datetime.now(tz=UTC)
        run = repository.create_generation_run(
            run_id=str(uuid.uuid4()), application_id=application_id, intake_id=intake_id,
            snapshot_id=None, snapshot_sha256=None, catalog_sha256=None,
            base_artifact_id=base_id, base_sha256="b" * 64,
            requested_by_id=actor_id, requested_at=now, created_at=now,
        )
        repository.create_generated_artifact(
            artifact_id=str(uuid.uuid4()), generation_run_id=run["id"],
            artifact_type="MANIFEST", filename="manifest.json", mime_type="application/json",
            size_bytes=2, sha256_hex="a" * 64, content_address="aa/" + "a" * 64,
            created_at=now,
        )
        with pytest.raises(DuplicateArtifactError):
            repository.create_generated_artifact(
                artifact_id=str(uuid.uuid4()), generation_run_id=run["id"],
                artifact_type="MANIFEST", filename="manifest.json", mime_type="application/json",
                size_bytes=2, sha256_hex="a" * 64, content_address="aa/" + "a" * 64,
                created_at=now,
            )
