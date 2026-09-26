"""C7.3 recovery, reconciliation, and retention-safe inventory tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.topology_recovery import (
    RecoveryConflictError,
    RecoveryService,
)
from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake
from migration_intake.persistence.models_topology import GenerationRun, TopologyBaseArtifact
from migration_intake.persistence.repositories.topology import (
    GenerationConflictError,
    TopologyRepository,
)
from migration_intake.storage.filesystem import FilesystemStore


def seed_expired_run(session: Session, *, phase: str = "STORING") -> tuple[str, str, str]:
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
        )
    )
    session.flush()
    session.add(
        GenerationRun(
            id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            base_artifact_id=base_id,
            base_sha256="c" * 64,
            phase=phase,
            status=phase,
            row_version=2,
            semantic_input_hash="d" * 64,
            attempt_number=0,
            lease_token="expired-lease",
            lease_expires_at=now - timedelta(minutes=5),
            requested_by_id=actor_id,
            requested_at=now,
            created_at=now,
            approval_status="PENDING",
        )
    )
    session.commit()
    return run_id, actor_id, intake_id


def test_recovery_inventory_is_read_only_and_claims_only_expired_runs(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, intake_id = seed_expired_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")
    service = RecoveryService(factory, storage)

    inventory = service.inventory(intake_id=intake_id)
    assert inventory["runs"][0]["id"] == run_id
    assert inventory["runs"][0]["lease_expired"] is True
    claimed = service.claim_expired_run(run_id=run_id, actor_id=actor_id)

    assert claimed["lease_token"] != "expired-lease"
    assert claimed["phase"] == "STORING"
    with factory() as session:
        assert TopologyRepository(session).get_generation_run(run_id)["attempt_number"] == 0


def test_recovery_rejects_healthy_lease_and_never_deletes_objects(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    now = datetime.now(tz=UTC)
    with factory() as session:
        run_id, actor_id, _ = seed_expired_run(session)
        run = session.get(GenerationRun, run_id)
        run.lease_expires_at = now + timedelta(minutes=5)
        session.commit()
    storage = FilesystemStore(tmp_path / "artifacts")
    receipt = storage.store(__import__("io").BytesIO(b"retained"), "retained.bin")
    service = RecoveryService(factory, storage)

    with pytest.raises(RecoveryConflictError, match="healthy lease"):
        service.claim_expired_run(run_id=run_id, actor_id=actor_id)
    assert storage.exists(receipt.storage_key)


def test_inventory_marks_corrupt_finalized_artifact_unavailable(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, _, intake_id = seed_expired_run(session, phase="COMPLETED")
    storage = FilesystemStore(tmp_path / "artifacts")
    receipt = storage.store(__import__("io").BytesIO(b"trusted"), "diagram.drawio")
    with factory() as session:
        repository = TopologyRepository(session)
        repository.create_generated_artifact(
            artifact_id=str(uuid.uuid4()),
            generation_run_id=run_id,
            artifact_type="DIAGRAM",
            filename="diagram.drawio",
            mime_type="application/xml",
            size_bytes=7,
            sha256_hex=hashlib.sha256(b"trusted").hexdigest(),
            content_address=receipt.storage_key,
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
    path = storage._resolve_key(receipt.storage_key)
    path.write_bytes(b"corrupt")

    inventory = RecoveryService(factory, storage).inventory(intake_id=intake_id)

    artifact = inventory["runs"][0]["artifacts"][0]
    assert artifact["available"] is True
    assert artifact["verified"] is False
    assert storage.exists(receipt.storage_key)


def test_reconcile_returns_pinned_input_without_mutable_answer_sql(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_expired_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")
    statements: list[str] = []
    from sqlalchemy import event

    def tripwire(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())
        if "ans_instances" in statement.lower() or "ans_revisions" in statement.lower():
            raise AssertionError("recovery queried mutable answers")

    event.listen(tmp_engine, "before_cursor_execute", tripwire)
    try:
        result = RecoveryService(factory, storage).reconcile_run(run_id=run_id, actor_id=actor_id)
    finally:
        event.remove(tmp_engine, "before_cursor_execute", tripwire)

    assert result["run_id"] == run_id
    assert result["requires_replay_from_input"] is False


def test_old_worker_token_cannot_advance_recovered_run(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_expired_run(session)
    storage = FilesystemStore(tmp_path / "artifacts")
    claimed = RecoveryService(factory, storage).claim_expired_run(run_id=run_id, actor_id=actor_id)

    with factory() as session:
        repository = TopologyRepository(session)
        with pytest.raises(GenerationConflictError, match="lease"):
            repository.transition_leased_generation_phase(
                run_id=run_id,
                expected_row_version=2,
                expected_phase="STORING",
                new_phase="VERIFYING",
                lease_token="expired-lease",
            )

    assert claimed["lease_token"] != "expired-lease"


def test_fail_abandoned_run_preserves_original_phase_and_input_identity(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_expired_run(session, phase="RENDERING")
    result = RecoveryService(factory, FilesystemStore(tmp_path / "artifacts")).fail_abandoned_run(
        run_id=run_id, actor_id=actor_id
    )

    assert result["phase"] == "FAILED"
    assert result["readiness_json"] == {"failure_phase": "RENDERING", "recovered": True}
    assert result["input_id"] is None


def test_recovery_attempt_limit_is_fail_closed(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "store")
    with factory() as session:
        run_id, actor_id, _ = seed_expired_run(session)
        session.get(GenerationRun, run_id).attempt_number = RecoveryService.MAX_RECOVERY_ATTEMPTS
        session.commit()
    with pytest.raises(RecoveryConflictError, match="attempt limit"):
        RecoveryService(factory, storage).claim_expired_run(
            run_id=run_id, actor_id=actor_id
        )


def test_partial_bundle_reconciliation_is_diagnostic_only(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    with factory() as session:
        run_id, actor_id, _ = seed_expired_run(session, phase="STORING")
    storage = FilesystemStore(tmp_path / "artifacts")
    receipt = storage.store(__import__("io").BytesIO(b"diagram"), "diagram.drawio")
    with factory() as session:
        TopologyRepository(session).create_generated_artifact(
            artifact_id=str(uuid.uuid4()),
            generation_run_id=run_id,
            artifact_type="DIAGRAM",
            filename="diagram.drawio",
            mime_type="application/xml",
            size_bytes=7,
            sha256_hex=hashlib.sha256(b"diagram").hexdigest(),
            content_address=receipt.storage_key,
            created_at=datetime.now(tz=UTC),
        )
        session.commit()

    service = RecoveryService(factory, storage)
    result = service.reconcile_run(run_id=run_id, actor_id=actor_id)

    assert result["deletion_enabled"] is False
    assert len(result["artifacts"]) == 1
    with factory() as session:
        assert TopologyRepository(session).get_generation_run(run_id)["phase"] == "STORING"
    assert storage.exists(receipt.storage_key)
