"""Persisted C8.1 review, integrity, and CAS tests."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.topology_review import (
    TopologyReviewError,
    TopologyReviewService,
)
from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake
from migration_intake.persistence.models_topology import (
    GeneratedArtifact,
    GenerationRun,
    TopologyBaseArtifact,
    TopologyCompatibility,
    TopologyInput,
    TopologyReview,
)
from migration_intake.storage.filesystem import FilesystemStore


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def seed_reviewable_bundle(
    session: Session,
    storage: FilesystemStore,
    *,
    status: str = "READY_FOR_REVIEW",
    warnings: list[str] | None = None,
) -> dict[str, str]:
    now = datetime.now(tz=UTC)
    actor_id, app_id, intake_id, catalog_id, base_id, input_id, run_id = (
        str(uuid.uuid4()) for _ in range(7)
    )
    session.add(Actor(id=actor_id, display_name="Synthetic reviewer", created_at=now))
    session.add(
        Application(
            id=app_id,
            state="ACTIVE",
            display_name="Synthetic application",
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
            source_sha256=_hash(catalog_id.encode()),
            compiler_version="1.0.0",
            catalog_hash=_hash((catalog_id + "catalog").encode()),
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
    base_sha = "c" * 64
    compatibility_id = str(uuid.uuid4())
    compatibility_key = _hash(compatibility_id.encode())
    compatibility_result_hash = _hash((compatibility_id + "result").encode())
    session.add(
        TopologyBaseArtifact(
            id=base_id,
            application_id=app_id,
            intake_id=intake_id,
            filename="base.drawio",
            mime_type="application/xml",
            size_bytes=1,
            sha256_hex=base_sha,
            content_address="cc/" + base_sha,
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
            selection_json={"contexts": [{"environment": "PROD", "site_id": "SITE_A"}]},
            selection_hash="e" * 64,
            compatibility_id=compatibility_id,
        )
    )
    session.flush()
    session.add(
        TopologyCompatibility(
            id=compatibility_id,
            base_artifact_id=base_id,
            base_sha256=base_sha,
            profile_id="SYNTHETIC_LABEL_ONLY",
            profile_version="1.0.0",
            profile_hash="d" * 64,
            selection_json={"contexts": [{"environment": "PROD", "site_id": "SITE_A"}]},
            selection_hash="e" * 64,
            capability="LABEL_ONLY",
            parser_policy_hash="1" * 64,
            compatibility_key=compatibility_key,
            result_json={},
            result_hash=compatibility_result_hash,
            checked_by_id=actor_id,
            checked_at=now,
        )
    )
    session.flush()
    session.add(
        TopologyInput(
            id=input_id,
            application_id=app_id,
            intake_id=intake_id,
            mode="OFFICIAL_SNAPSHOT",
            projection_json="{}",
            projection_sha256="f" * 64,
            selection_json={"contexts": [{"environment": "PROD", "site_id": "SITE_A"}]},
            selection_sha256="e" * 64,
            capability="LABEL_ONLY",
            base_artifact_id=base_id,
            base_sha256=base_sha,
            compatibility_id=compatibility_id,
            compatibility_key=compatibility_key,
            compatibility_result_hash=compatibility_result_hash,
            profile_id="SYNTHETIC_LABEL_ONLY",
            profile_hash="d" * 64,
            catalog_sha256="b" * 64,
            generator_version="c8-test",
            parser_policy_hash="1" * 64,
            layout_policy_hash="2" * 64,
            result_policy_hash="3" * 64,
            semantic_input_hash="4" * 64,
            captured_by_id=actor_id,
            captured_at=now,
        )
    )
    session.flush()
    readiness = {"status": status, "blockers": [], "warnings": warnings or []}
    manifest_bytes = json.dumps({"result_status": status}, separators=(",", ":")).encode()
    contents = {
        "DIAGRAM": b"<mxfile><diagram>synthetic</diagram></mxfile>",
        "GAP_REPORT": b"<html>synthetic</html>",
        "MANIFEST": manifest_bytes,
    }
    manifest_hash = _hash(manifest_bytes)
    session.add(
        GenerationRun(
            id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            base_artifact_id=base_id,
            base_sha256=base_sha,
            input_id=input_id,
            mode="OFFICIAL_SNAPSHOT",
            capability="LABEL_ONLY",
            authority="OFFICIAL_SNAPSHOT",
            phase="COMPLETED",
            row_version=1,
            semantic_input_hash="4" * 64,
            requested_by_id=actor_id,
            requested_at=now,
            completed_at=now,
            created_at=now,
            status=status,
            readiness_json=readiness,
            manifest_hash=manifest_hash,
            approval_status="PENDING",
        )
    )
    session.flush()
    for artifact_type, content in contents.items():
        receipt = storage.store(io.BytesIO(content), f"{artifact_type.lower()}.bin")
        session.add(
            GeneratedArtifact(
                id=str(uuid.uuid4()),
                generation_run_id=run_id,
                artifact_type=artifact_type,
                filename=f"{artifact_type.lower()}.bin",
                mime_type=receipt.media_type,
                size_bytes=receipt.size_bytes,
                sha256_hex=receipt.sha256_hex,
                content_address=receipt.storage_key,
                created_at=now,
            )
        )
    session.commit()
    return {
        "actor_id": actor_id,
        "actor_capabilities": {
            "TOPOLOGY_RUN_APPROVE",
            "TOPOLOGY_RUN_REJECT",
            "TOPOLOGY_RUN_SUPERSEDE",
        },
        "application_id": app_id,
        "intake_id": intake_id,
        "run_id": run_id,
    }


def test_review_approves_complete_bundle_and_records_audit(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)

    result = TopologyReviewService(factory, storage).review_run(
        **context,
        decision="APPROVED",
        rationale="Reviewed the immutable bundle.",
    )

    assert result["approval_status"] == "APPROVED"
    with factory() as session:
        review = session.query(TopologyReview).filter_by(run_id=context["run_id"]).one()
        assert review.decision == "APPROVED"
        assert review.self_review == 1


def test_review_requires_warning_rationale(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage, warnings=["UNRESOLVED_MARKER"])

    with pytest.raises(TopologyReviewError, match="warning"):
        TopologyReviewService(factory, storage).review_run(
            **context,
            decision="APPROVED",
            rationale="Reviewed the immutable bundle.",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("mode", "DRAFT_PREVIEW"), ("authority", "LEGACY_UNPINNED")],
)
def test_review_rejects_non_official_authority(tmp_engine, tmp_path, field, value):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
        setattr(session.get(GenerationRun, context["run_id"]), field, value)
        session.commit()

    with pytest.raises(TopologyReviewError, match="Preview or legacy"):
        TopologyReviewService(factory, storage).review_run(
            **context,
            decision="APPROVED",
            rationale="Invalid authority must fail closed.",
        )


def test_review_rejects_readiness_blocker(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
        session.get(GenerationRun, context["run_id"]).readiness_json = {
            "status": "READY_FOR_REVIEW",
            "blockers": ["MISSING_REQUIRED_SLOT"],
            "warnings": [],
        }
        session.commit()

    with pytest.raises(TopologyReviewError, match="Blocking readiness"):
        TopologyReviewService(factory, storage).review_run(
            **context,
            decision="APPROVED",
            rationale="Blocker must fail closed.",
        )


def test_review_rejects_missing_capability(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
    context["actor_capabilities"] = set()

    with pytest.raises(TopologyReviewError, match="capability"):
        TopologyReviewService(factory, storage).review_run(
            **context,
            decision="APPROVED",
            rationale="Unauthorized review must fail closed.",
        )


@pytest.mark.parametrize("artifact_type", ["DIAGRAM", "GAP_REPORT"])
def test_review_rejects_corrupt_non_manifest_artifact(tmp_engine, tmp_path, artifact_type):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
        artifact = (
            session.query(GeneratedArtifact)
            .filter_by(generation_run_id=context["run_id"], artifact_type=artifact_type)
            .one()
        )
        path = tmp_path / "artifacts" / artifact.content_address
        path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(TopologyReviewError, match=r"(size|hash)"):
        TopologyReviewService(factory, storage).review_run(
            **context, decision="APPROVED", rationale="Must fail closed."
        )
    with factory() as session:
        assert session.query(TopologyReview).filter_by(run_id=context["run_id"]).count() == 0


@pytest.mark.parametrize("state", ["REJECTED", "SUPERSEDED"])
def test_review_rejects_ineligible_base_without_mutation(tmp_engine, tmp_path, state):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
        run = session.get(GenerationRun, context["run_id"])
        session.get(TopologyBaseArtifact, run.base_artifact_id).review_state = state
        session.commit()
    with pytest.raises(TopologyReviewError, match="base"):
        TopologyReviewService(factory, storage).review_run(
            **context, decision="APPROVED", rationale="Must fail closed."
        )
    with factory() as session:
        assert session.query(TopologyReview).filter_by(run_id=context["run_id"]).count() == 0


def test_review_rejects_stale_compatibility_without_mutation(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
        run = session.get(GenerationRun, context["run_id"])
        compatibility = session.get(
            TopologyCompatibility,
            session.get(TopologyInput, run.input_id).compatibility_id,
        )
        compatibility.result_hash = "9" * 64
        session.commit()
    with pytest.raises(TopologyReviewError, match="stale"):
        TopologyReviewService(factory, storage).review_run(
            **context, decision="APPROVED", rationale="Must fail closed."
        )
    with factory() as session:
        assert session.query(TopologyReview).filter_by(run_id=context["run_id"]).count() == 0


@pytest.mark.parametrize("rationale", ["", "   ", 1])
def test_review_rejects_invalid_warning_rationale(tmp_engine, tmp_path, rationale):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage, warnings=["WARNING-1"])
    with pytest.raises(TopologyReviewError, match="nonblank"):
        TopologyReviewService(factory, storage).review_run(
            **context,
            decision="APPROVED",
            rationale="Reviewed.",
            issue_decisions={"WARNING-1": rationale},
        )


def test_review_rejects_unknown_warning_decision(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage, warnings=["WARNING-1"])
    with pytest.raises(TopologyReviewError, match="Unknown"):
        TopologyReviewService(factory, storage).review_run(
            **context,
            decision="APPROVED",
            rationale="Reviewed.",
            issue_decisions={"WARNING-1": "accepted", "UNKNOWN": "invalid"},
        )


def test_review_rejects_manifest_receipt_tampering(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
        run = session.get(GenerationRun, context["run_id"])
        manifest = (
            session.query(GeneratedArtifact)
            .filter_by(generation_run_id=run.id, artifact_type="MANIFEST")
            .one()
        )
        manifest.size_bytes += 1
        session.commit()

    with pytest.raises(TopologyReviewError, match=r"(Manifest|artifact) size"):
        TopologyReviewService(factory, storage).review_run(
            **context,
            decision="APPROVED",
            rationale="Receipt is intentionally invalid.",
        )


def test_download_rejects_tampered_approved_artifact(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
    service = TopologyReviewService(factory, storage)
    service.review_run(**context, decision="APPROVED", rationale="Approved bundle.")

    with factory() as session:
        artifact = (
            session.query(GeneratedArtifact)
            .filter_by(generation_run_id=context["run_id"], artifact_type="DIAGRAM")
            .one()
        )
    with storage.retrieve(artifact.content_address) as stream:
        original = stream.read()
    storage_path = tmp_path / "artifacts" / artifact.content_address
    storage_path.write_bytes(original + b"tampered")

    with pytest.raises(TopologyReviewError, match=r"(size|hash)"):
        service.verified_artifact(
            run_id=context["run_id"],
            application_id=context["application_id"],
            intake_id=context["intake_id"],
            artifact_type="DIAGRAM",
        )


def test_concurrent_review_has_one_cas_winner(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
    service = TopologyReviewService(factory, storage)

    service.review_run(**context, decision="APPROVED", rationale="First review.")
    with pytest.raises(TopologyReviewError, match="already been reviewed"):
        service.review_run(**context, decision="REJECTED", rationale="Stale review.")


def test_supersession_links_approved_runs_and_records_audit(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        predecessor = seed_reviewable_bundle(session, storage)
        successor = seed_reviewable_bundle(session, storage)
        successor["application_id"] = predecessor["application_id"]
        successor["intake_id"] = predecessor["intake_id"]
        predecessor_run = session.get(GenerationRun, predecessor["run_id"])
        successor_run = session.get(GenerationRun, successor["run_id"])
        for run in (predecessor_run, successor_run):
            run.application_id = predecessor["application_id"]
            run.intake_id = predecessor["intake_id"]
            run.approval_status = "APPROVED"
        successor_run.attempt_number = 1
        successor_run.semantic_input_hash = predecessor_run.semantic_input_hash
        successor_run.base_artifact_id = predecessor_run.base_artifact_id
        successor_run.base_sha256 = predecessor_run.base_sha256
        successor_run.input_id = predecessor_run.input_id
        successor_run.capability = predecessor_run.capability
        session.commit()

    result = TopologyReviewService(factory, storage).supersede_run(
        predecessor_run_id=predecessor["run_id"],
        successor_run_id=successor["run_id"],
        application_id=predecessor["application_id"],
        intake_id=predecessor["intake_id"],
        actor_id=predecessor["actor_id"],
        actor_capabilities={"TOPOLOGY_RUN_SUPERSEDE"},
        rationale="Approved successor replaces the predecessor.",
    )

    assert result["approval_status"] == "SUPERSEDED"
    assert result["superseded_by_id"] == successor["run_id"]


def test_supersession_rejects_self_and_missing_capability(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "artifacts")
    with factory() as session:
        context = seed_reviewable_bundle(session, storage)
        session.get(GenerationRun, context["run_id"]).approval_status = "APPROVED"
        session.commit()

    service = TopologyReviewService(factory, storage)
    with pytest.raises(TopologyReviewError, match="itself"):
        service.supersede_run(
            predecessor_run_id=context["run_id"],
            successor_run_id=context["run_id"],
            application_id=context["application_id"],
            intake_id=context["intake_id"],
            actor_id=context["actor_id"],
            actor_capabilities={"TOPOLOGY_RUN_SUPERSEDE"},
            rationale="Self supersession is invalid.",
        )
    with pytest.raises(TopologyReviewError, match="capability"):
        service.supersede_run(
            predecessor_run_id=context["run_id"],
            successor_run_id=str(uuid.uuid4()),
            application_id=context["application_id"],
            intake_id=context["intake_id"],
            actor_id=context["actor_id"],
            actor_capabilities=set(),
            rationale="Unauthorized supersession is invalid.",
        )
