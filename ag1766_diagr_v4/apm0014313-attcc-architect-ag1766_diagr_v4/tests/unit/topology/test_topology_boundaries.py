"""Regression tests for topology access, extraction, and artifact storage."""

from __future__ import annotations

import io
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.persistence.models import (
    Actor,
    Application,
    ApplicationIdentifier,
    CatalogRelease,
    Intake,
)
from migration_intake.persistence.models_snapshots import IntakeSnapshot
from migration_intake.persistence.models_topology import (
    GeneratedArtifact,
    GenerationRun,
    TopologyBaseArtifact,
    TopologyInput,
)
from migration_intake.persistence.repositories.topology import TopologyRepository
from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.topology.adapter import TopologyData, extract_topology_data
from migration_intake.topology.fill import FillResult
from migration_intake.application.dto import ActorContext
from migration_intake.application.services.topology_generation import (
    TopologyApprovalError,
    TopologyGenerationService,
)


def _seed_run(session: Session) -> tuple[str, str, str, str]:
    """Create two intakes and a run owned by the first intake."""
    now = datetime.now(tz=UTC)
    actor_id = str(uuid.uuid4())
    application_id = str(uuid.uuid4())
    catalog_id = str(uuid.uuid4())
    intake_id = str(uuid.uuid4())
    other_intake_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    base_id = str(uuid.uuid4())

    session.add(Actor(id=actor_id, display_name="Topology Test Actor", created_at=now))
    session.add(
        Application(
            id=application_id,
            state="ACTIVE",
            display_name="Topology Test Application",
            created_at=now,
            updated_at=now,
            row_version=1,
            created_by_id=actor_id,
        )
    )
    session.add(
        ApplicationIdentifier(
            id=str(uuid.uuid4()),
            application_id=application_id,
            identifier_type="CORRELATION",
            raw_value="CORR-001",
            normalized_value="CORR001",
            created_at=now,
        )
    )
    session.add(
        CatalogRelease(
            id=catalog_id,
            semantic_version="1.0.0",
            source_filename="synthetic-catalog.yaml",
            source_sha256="b" * 64,
            compiler_version="1.0",
            pub_state="PUBLISHED",
            published_at=now,
            created_at=now,
        )
    )
    session.add_all(
        [
            Intake(
                id=intake_id,
                application_id=application_id,
                catalog_id=catalog_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            ),
            Intake(
                id=other_intake_id,
                application_id=application_id,
                catalog_id=catalog_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            ),
        ]
    )
    session.flush()
    session.add(
        TopologyBaseArtifact(
            id=base_id,
            application_id=application_id,
            intake_id=intake_id,
            filename="synthetic.drawio",
            mime_type="application/vnd.jgraph.mxfile+xml",
            size_bytes=12,
            sha256_hex="a" * 64,
            content_address="aa/" + "a" * 64,
            uploaded_by_id=actor_id,
            uploaded_at=now,
            created_at=now,
        )
    )
    session.flush()
    session.add(
        GenerationRun(
            id=run_id,
            application_id=application_id,
            intake_id=intake_id,
            snapshot_id=None,
            snapshot_sha256=None,
            catalog_sha256=None,
            base_artifact_id=base_id,
            base_sha256="a" * 64,
            status="READY_FOR_REVIEW",
            approval_status="PENDING",
            requested_by_id=actor_id,
            requested_at=now,
            created_at=now,
        )
    )
    session.commit()
    return application_id, intake_id, other_intake_id, run_id


def test_generation_run_lookup_requires_application_and_intake_scope(
    tmp_engine,
) -> None:
    """A valid run is invisible when addressed through another intake."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, other_intake_id, run_id = _seed_run(session)
        repository = TopologyRepository(session)

        assert repository.get_generation_run_for_intake(
            run_id, application_id, intake_id
        ) is not None
        assert repository.get_generation_run_for_intake(
            run_id, application_id, other_intake_id
        ) is None
        assert repository.get_generation_run_for_intake(
            run_id, str(uuid.uuid4()), intake_id
        ) is None


def test_filesystem_store_round_trip(tmp_path: Path) -> None:
    """Topology artifact bytes survive a real content-addressed round trip."""
    store = FilesystemStore(tmp_path / "topology")
    content = b"<mxfile compressed=\"false\"><diagram>test</diagram></mxfile>"

    receipt = store.store(io.BytesIO(content), "topology.drawio")

    assert receipt.size_bytes == len(content)
    assert receipt.sha256_hex in receipt.storage_key
    with store.retrieve(receipt.storage_key) as stream:
        assert stream.read() == content


def test_extract_topology_data_preserves_missing_tokens(
    tmp_engine,
) -> None:
    """The adapter reports absent facts instead of inventing values."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        _, intake_id, _, _ = _seed_run(session)
        data = extract_topology_data(session, intake_id)

    assert data.correlation_id == "CORR-001"
    assert data.tokens["app_name"] == "Topology Test Application"
    assert "environment" in data.missing_tokens
    assert "region" in data.missing_tokens


class FailingSession:
    """Minimal session double for proving adapter errors are not hidden."""

    def __init__(self, real_session: Session) -> None:
        self._real_session = real_session
        self.calls = 0

    def execute(self, statement):
        self.calls += 1
        if self.calls == 3:
            raise RuntimeError("synthetic database failure")
        return self._real_session.execute(statement)


def test_extract_topology_data_propagates_answer_query_failure(
    tmp_engine,
) -> None:
    """Database failures must not be converted into misleading missing tokens."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        _, intake_id, _, _ = _seed_run(session)
        with pytest.raises(RuntimeError, match="synthetic database failure"):
            extract_topology_data(FailingSession(session), intake_id)  # type: ignore[arg-type]


def test_topology_service_upload_round_trips_base_diagram(
    tmp_engine,
    tmp_path: Path,
) -> None:
    """Uploading a valid base diagram persists metadata and retrievable bytes."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, _, _ = _seed_run(session)

    service = TopologyGenerationService(session_factory, tmp_path)
    actor = ActorContext(actor_id=_actor_id_for_application(tmp_engine, application_id))
    content = b'<mxfile compressed="false"><diagram name="Topology" /></mxfile>'

    result = service.upload_base_diagram(
        intake_id,
        content,
        "uploaded.drawio",
        actor,
    )

    assert result["intake_id"] == intake_id
    assert service.get_base_artifact_content(result["id"]) == (
        content,
        "uploaded.drawio",
        "application/vnd.jgraph.mxfile+xml",
    )


def test_topology_service_marks_failed_run_when_base_content_is_unavailable(
    tmp_engine,
    tmp_path: Path,
) -> None:
    """A generation exception leaves an auditable FAILED run behind."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, _, _ = _seed_run(session)

    service = TopologyGenerationService(session_factory, tmp_path)
    actor = ActorContext(actor_id=_actor_id_for_application(tmp_engine, application_id))

    with pytest.raises(FileNotFoundError):
        service.generate_topology(intake_id, _base_id_for_intake(tmp_engine, intake_id), actor)

    runs = service.list_generation_runs(intake_id)
    assert len(runs) == 2
    failed_run = next(run for run in runs if run["status"] == "FAILED")
    assert failed_run["error_message"]


def test_topology_service_rejects_approval_of_draft_preview(
    tmp_engine,
    tmp_path: Path,
) -> None:
    """Live-data draft previews are not authoritative approval inputs."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, _, run_id = _seed_run(session)

    service = TopologyGenerationService(session_factory, tmp_path)
    actor = ActorContext(
        actor_id=_actor_id_for_application(tmp_engine, application_id),
        role_codes=frozenset({"TOPOLOGY_RUN_APPROVE"}),
    )

    with pytest.raises(TopologyApprovalError, match="[Pp]review"):
        service.approve_generation_run(
            run_id,
            application_id,
            intake_id,
            actor,
            approved=True,
            rationale="Reviewed draft output",
        )


def test_topology_service_approves_completed_snapshot_run(
    tmp_engine,
    tmp_path: Path,
) -> None:
    """An official completed run records its reviewer and rationale."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, _, run_id = _seed_run(session)
        actor_id = _actor_id_for_application(tmp_engine, application_id)
        snapshot_id = str(uuid.uuid4())
        session.add(
            IntakeSnapshot(
                id=snapshot_id,
                intake_id=intake_id,
                catalog_id=str(session.get(Intake, intake_id).catalog_id),
                created_by_id=actor_id,
                schema_version="1.0",
                catalog_sha256="b" * 64,
                canonical_json="{}",
                sha256_hex="c" * 64,
                created_at=datetime.now(tz=UTC),
            )
        )
        run = session.get(GenerationRun, run_id)
        run.snapshot_id = snapshot_id
        run.snapshot_sha256 = "c" * 64
        run.catalog_sha256 = "b" * 64
        input_id = str(uuid.uuid4())
        session.add(
            TopologyInput(
                id=input_id,
                application_id=application_id,
                intake_id=intake_id,
                mode="OFFICIAL_SNAPSHOT",
                projection_json="{}",
                projection_sha256="d" * 64,
                selection_json={},
                selection_sha256="e" * 64,
                capability="LABEL_ONLY",
                base_artifact_id=run.base_artifact_id,
                base_sha256=run.base_sha256,
                profile_id="SYNTHETIC_LABEL_ONLY",
                profile_hash="f" * 64,
                catalog_sha256="b" * 64,
                generator_version="test",
                parser_policy_hash="1" * 64,
                layout_policy_hash="2" * 64,
                result_policy_hash="3" * 64,
                semantic_input_hash="4" * 64,
                captured_by_id=actor_id,
                captured_at=datetime.now(tz=UTC),
            )
        )
        run.input_id = input_id
        run.mode = "OFFICIAL_SNAPSHOT"
        run.capability = "LABEL_ONLY"
        run.authority = "OFFICIAL_SNAPSHOT"
        run.phase = "COMPLETED"
        run.semantic_input_hash = "4" * 64
        run.readiness_json = {"status": "READY_FOR_REVIEW", "blockers": [], "warnings": []}
        store = FilesystemStore(tmp_path / "topology")
        artifact_contents = {
            "DIAGRAM": b"<mxfile />",
            "GAP_REPORT": b"<html />",
            "MANIFEST": b'{"result_status":"READY_FOR_REVIEW"}',
        }
        for artifact_type, content in artifact_contents.items():
            receipt = store.store(io.BytesIO(content), f"{artifact_type.lower()}.bin")
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
                    created_at=datetime.now(tz=UTC),
                )
            )
            if artifact_type == "MANIFEST":
                run.manifest_hash = receipt.sha256_hex
        run.status = "READY_FOR_REVIEW"
        session.commit()

    service = TopologyGenerationService(session_factory, tmp_path)
    actor = ActorContext(
        actor_id=actor_id,
        role_codes=frozenset({"TOPOLOGY_RUN_APPROVE"}),
    )
    result = service.approve_generation_run(
        run_id,
        application_id,
        intake_id,
        actor,
        approved=True,
        rationale="Reviewed against the frozen canonical snapshot",
    )

    assert result["approval_status"] == "APPROVED"
    assert result["approved_by_id"] == actor_id
    assert result["approval_rationale"] == "Reviewed against the frozen canonical snapshot"


def test_topology_service_generates_pinned_artifacts_from_snapshot(
    tmp_engine,
    tmp_path: Path,
) -> None:
    """Successful generation pins the snapshot and stores both artifacts."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, _, _ = _seed_run(session)
        actor_id = _actor_id_for_application(tmp_engine, application_id)
        catalog_id = session.get(Intake, intake_id).catalog_id
        snapshot_json = '{"answers":{},"application_id":"' + application_id + '"}'
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        session.add(
            IntakeSnapshot(
                id=str(uuid.uuid4()),
                intake_id=intake_id,
                catalog_id=str(catalog_id),
                created_by_id=actor_id,
                schema_version="1.0",
                catalog_sha256="b" * 64,
                canonical_json=snapshot_json,
                sha256_hex=snapshot_hash,
                created_at=datetime.now(tz=UTC),
            )
        )
        intake = session.get(Intake, intake_id)
        intake.state = "FROZEN"
        session.commit()

    service = TopologyGenerationService(session_factory, tmp_path)
    actor = ActorContext(actor_id=actor_id)
    base_content = (
        b'<mxfile compressed="false"><diagram name="Topology">'
        b"<mxGraphModel><root><mxCell id=\"label\" value=\"{app_name}\"/>"
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    base = service.upload_base_diagram(
        intake_id,
        base_content,
        "base.drawio",
        actor,
    )

    run = service.generate_topology(intake_id, base["id"], actor)

    assert run["status"] == "READY_FOR_REVIEW"
    assert run["snapshot_id"] is not None
    assert run["snapshot_sha256"] == snapshot_hash
    assert run["catalog_sha256"] == "b" * 64

    artifacts = service.get_run_artifacts(run["id"])
    assert {artifact["artifact_type"] for artifact in artifacts} == {
        "DIAGRAM",
        "GAP_REPORT",
    }
    for artifact in artifacts:
        content = service.get_artifact_content(artifact["id"])
        assert content is not None
        assert hashlib.sha256(content[0]).hexdigest() == artifact["sha256_hex"]


def test_topology_service_persists_ready_status_for_clean_generation(
    tmp_engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean generation persists READY_FOR_REVIEW from the shared status policy."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, _, _ = _seed_run(session)
        actor_id = _actor_id_for_application(tmp_engine, application_id)

    service = TopologyGenerationService(session_factory, tmp_path)
    actor = ActorContext(actor_id=actor_id)
    base_content = (
        b'<mxfile compressed="false"><diagram name="Topology">'
        b"<mxGraphModel><root><mxCell id=\"label\" value=\"Application Name\"/>"
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    base = service.upload_base_diagram(
        intake_id,
        base_content,
        "base-clean.drawio",
        actor,
    )

    clean_topology_data = TopologyData(
        app_id=application_id,
        app_name="Topology Test Application",
        app_acronym="TTA",
        correlation_id="CORR-001",
        tokens={"app_name": "Topology Test Application"},
        missing_tokens=[],
        issues=[],
    )

    monkeypatch.setattr(
        "migration_intake.application.services.topology_generation.extract_topology_data",
        lambda _session, _intake_id: clean_topology_data,
    )
    monkeypatch.setattr(
        "migration_intake.application.services.topology_generation.fill_diagram",
        lambda _base_content, _tokens: FillResult(
            success=True,
            filled_xml=base_content,
            mutations=[
                {
                    "slot_name": "app_name",
                    "cell_id": "label",
                    "original_value": "Application Name",
                    "new_value": "Topology Test Application",
                }
            ],
            errors=[],
            warnings=[],
        ),
    )

    run = service.generate_topology(intake_id, base["id"], actor)
    assert run["status"] == "READY_FOR_REVIEW"


def test_topology_service_uses_haf_pipeline_for_haf_role_templates(
    tmp_engine,
    tmp_path: Path,
) -> None:
    """HAF templates generated through the legacy route use the HAF fill path."""
    session_factory = sessionmaker(bind=tmp_engine)
    with session_factory() as session:
        application_id, intake_id, _, _ = _seed_run(session)
        actor_id = _actor_id_for_application(tmp_engine, application_id)

    service = TopologyGenerationService(session_factory, tmp_path)
    actor = ActorContext(actor_id=actor_id)
    base_content = (
        b'<mxfile compressed="false"><diagram name="Topology">'
        b"<mxGraphModel><root>"
        b'<mxCell id="0" haf-role="root_layer"/>'
        b'<mxCell id="1" parent="0" vertex="1" haf-role="header_line" '
        b'value="AT&amp;T - NEEDS-OUTPOST-ID"><mxGeometry x="0" y="0" width="10" '
        b'height="10" as="geometry"/></mxCell>'
        b'<mxCell id="2" parent="0" vertex="1" haf-role="azure_apps_slot" '
        b'value="INITIAL-SLOT-VALUE"><mxGeometry x="0" y="0" width="10" '
        b'height="10" as="geometry"/></mxCell>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    base = service.upload_base_diagram(
        intake_id,
        base_content,
        "base-haf.drawio",
        actor,
    )

    run = service.generate_topology(intake_id, base["id"], actor)

    artifacts = service.get_run_artifacts(run["id"])
    diagram = next(a for a in artifacts if a["artifact_type"] == "DIAGRAM")
    report = next(a for a in artifacts if a["artifact_type"] == "GAP_REPORT")
    diagram_content = service.get_artifact_content(diagram["id"])
    report_content = service.get_artifact_content(report["id"])
    assert diagram_content is not None
    assert report_content is not None
    diagram_text = diagram_content[0].decode("utf-8")
    report_text = report_content[0].decode("utf-8")

    assert "INITIAL-SLOT-VALUE" not in diagram_text
    assert "None found in source data" in diagram_text
    assert "outpost_id" in report_text
    assert run["status"] == "READY_FOR_REVIEW"


def _actor_id_for_application(engine, application_id: str) -> str:
    from sqlalchemy import select

    with sessionmaker(bind=engine)() as session:
        actor_id = session.execute(
            select(Application.created_by_id).where(Application.id == application_id)
        ).scalar_one()
    return str(actor_id)


def _base_id_for_intake(engine, intake_id: str) -> str:
    from sqlalchemy import select

    with sessionmaker(bind=engine)() as session:
        base_id = session.execute(
            select(TopologyBaseArtifact.id).where(
                TopologyBaseArtifact.intake_id == intake_id
            )
        ).scalar_one()
    return str(base_id)
