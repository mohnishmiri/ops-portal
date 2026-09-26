"""C7.1 persisted snapshot/capture authority and runner integration."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.base_diagram import BaseDiagramService
from migration_intake.application.services.topology_runner import (
    GovernedRunnerError,
    GovernedTopologyRunner,
    PersistedLabelRenderer,
)
from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    ApplicationIdentifier,
    AuditEvent,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_snapshots import IntakeSnapshot
from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.topology import TopologyRepository
from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.topology.contracts import RenderCapability, serialize_snapshot_document
from migration_intake.topology.profiles import load_profile
from migration_intake.topology.scope import ContextKey, ScopeSelection
from migration_intake.topology.strict_projection import StrictFactMapping


def v3_document(
    app_id: str, intake_id: str, actor_id: str, catalog_id: str, *, name: str = "Synthetic"
) -> dict[str, object]:
    return {
        "schema_version": "3.0.0",
        "application": {"id": app_id, "name": name, "acronym": "SYN", "identifiers": []},
        "catalog": {
            "id": catalog_id,
            "version": "1.0.0",
            "source_sha256": "a" * 64,
            "catalog_hash": "e" * 64,
            "compiler_version": "1.0.0",
        },
        "intake": {
            "id": intake_id,
            "state": "FROZEN",
            "frozen_at": "2026-09-19T00:00:00.000Z",
            "frozen_by": actor_id,
            "row_version": 1,
            "content_epoch": 1,
        },
        "answers": [
            {
                "question_code": "CTL-002",
                "response_type": "TEXT_PAIR",
                "value": {"first": name, "second": "SYN"},
                "confirm_state": "CONFIRMED",
                "review_state": "CONFIRMED",
                "revision_number": 1,
                "provenance_references": [],
            }
        ],
        "interface_register": {"interface_epoch": 1, "rows": []},
        "resources": [],
        "relationships": [],
        "wave_util_rows": [],
        "permitted_gaps": [],
    }


def base_bytes(*, structural: bool = False) -> bytes:
    marker = b"{{APPLICATION_NAME}}"
    return (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" value="' + marker + b'"/>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )


def seed(
    session: Session,
    storage: FilesystemStore,
    *,
    snapshot_schema: str = "3.0.0",
    capability: RenderCapability = RenderCapability.LABEL_ONLY,
) -> dict[str, str]:
    now = datetime.now(tz=UTC)
    actor_id, app_id, catalog_id, intake_id, snapshot_id = (str(uuid.uuid4()) for _ in range(5))
    section_id, question_id, instance_id, revision_id = (str(uuid.uuid4()) for _ in range(4))
    session.add(Actor(id=actor_id, display_name="Synthetic actor", created_at=now))
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
            catalog_hash="e" * 64,
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
            created_by_id=actor_id,
        )
    )
    session.flush()
    selected = ScopeSelection(
        app_id, intake_id, (ContextKey("PROD", "SITE_A"),), "combined-overview-with-details"
    )
    if snapshot_schema == "3.0.0":
        contract = serialize_snapshot_document(v3_document(app_id, intake_id, actor_id, catalog_id))
        snapshot_json, snapshot_hash = contract.canonical_json, contract.sha256_hex
    else:
        snapshot_json = json.dumps(
            {"schema_version": snapshot_schema}, sort_keys=True, separators=(",", ":")
        )
        snapshot_hash = __import__("hashlib").sha256(snapshot_json.encode()).hexdigest()
    session.add(
        IntakeSnapshot(
            id=snapshot_id,
            intake_id=intake_id,
            catalog_id=catalog_id,
            schema_version=snapshot_schema,
            catalog_sha256="a" * 64,
            canonical_json=snapshot_json,
            sha256_hex=snapshot_hash,
            created_at=now,
            created_by_id=actor_id,
        )
    )
    session.add(
        CatalogSection(
            id=section_id,
            release_id=catalog_id,
            section_code="CTL",
            display_name="Control",
            display_order=1,
        )
    )
    session.flush()
    session.add(
        CatalogQuestion(
            id=question_id,
            section_id=section_id,
            question_code="CTL-002",
            question_text="Application name and acronym",
            response_type="TEXT_PAIR",
            required_level="REQUIRED",
            collection_mode="MANUAL",
            display_order=1,
        )
    )
    session.flush()
    session.add(
        AnswerInstance(
            id=instance_id,
            intake_id=intake_id,
            question_id=question_id,
            created_at=now,
            current_rev_id=None,
            applicability="APPLICABLE",
            value_state="ANSWERED",
            review_state="CONFIRMED",
            updated_at=now,
            row_version=1,
        )
    )
    session.flush()
    session.add(
        AnswerRevision(
            id=revision_id,
            instance_id=instance_id,
            revision_number=1,
            response_json={"first": "Synthetic", "second": "SYN"},
            confirm_state="CONFIRMED",
            authored_at=now,
            authored_by_id=actor_id,
            response_schema_version="1.0",
        )
    )
    session.flush()
    session.get(AnswerInstance, instance_id).current_rev_id = revision_id
    governance = BaseDiagramService(TopologyRepository(session), storage)
    upload = governance.upload_base_diagram(
        application_id=app_id,
        intake_id=intake_id,
        filename="base.xml",
        diagram_bytes=base_bytes(structural=capability == RenderCapability.STRUCTURAL),
        uploaded_by_id=actor_id,
    )
    checked = governance.check_compatibility(
        base_artifact_id=upload.base_artifact_id,
        profile=load_profile(
            "SYNTHETIC_STRUCTURAL"
            if capability == RenderCapability.STRUCTURAL
            else "SYNTHETIC_LABEL_ONLY"
        ),
        selection=selected,
        capability=capability,
        partition_views={selected.ordered_contexts[0]: "Overview"},
        checked_by_id=actor_id,
        expected_row_version=1,
    )
    governance.approve_base_diagram(
        base_artifact_id=upload.base_artifact_id,
        selection=selected,
        capability=capability,
        partition_views={selected.ordered_contexts[0]: "Overview"},
        approved_by_id=actor_id,
        rationale="Synthetic C7 fixture",
        expected_row_version=checked.row_version,
    )
    compatibility = TopologyRepository(session).get_topology_compatibility(checked.compatibility_id)
    assert compatibility is not None
    session.commit()
    return {
        "actor": actor_id,
        "app": app_id,
        "catalog": catalog_id,
        "intake": intake_id,
        "base": upload.base_artifact_id,
        "snapshot": snapshot_id,
        "parser_policy": compatibility["parser_policy_hash"],
        "capability": capability.value,
    }


def selection(ids: dict[str, str]) -> ScopeSelection:
    return ScopeSelection(
        ids["app"], ids["intake"], (ContextKey("PROD", "SITE_A"),), "combined-overview-with-details"
    )


def mappings() -> tuple[StrictFactMapping, ...]:
    return (
        StrictFactMapping("CTL-002", "TEXT_PAIR", "application.name", "TEXT_PAIR.first"),
        StrictFactMapping("CTL-002", "TEXT_PAIR", "application.acronym", "TEXT_PAIR.second"),
    )


def options(ids: dict[str, str]) -> dict[str, object]:
    selected = selection(ids)
    return {
        "selection": selected,
        "partition_views": {selected.ordered_contexts[0]: "Overview"},
        "mappings": mappings(),
        "capability": RenderCapability(ids["capability"]),
        "base_artifact_id": ids["base"],
        "requested_by_id": ids["actor"],
        "generator_version": "c7-test",
        "parser_policy_hash": ids["parser_policy"],
        "layout_policy_hash": "0" * 64,
        "result_policy_hash": "1" * 64,
    }


def test_official_loads_hash_validated_v3_snapshot_and_duplicate_returns_original(
    tmp_engine, tmp_path
):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
    rendered: list[dict[str, object]] = []
    runner = GovernedTopologyRunner(factory, storage, rendered.append)

    first = runner.run_official(snapshot_id=ids["snapshot"], **options(ids))
    second = runner.run_official(snapshot_id=ids["snapshot"], **options(ids))

    assert first["id"] == second["id"]
    assert first["phase"] == "STORING"
    assert len(rendered) == 1
    assert rendered[0]["snapshot_id"] == ids["snapshot"]
    assert rendered[0]["capture_id"] is None
    with factory() as session:
        persisted = TopologyRepository(session).get_topology_input(str(rendered[0]["input_id"]))
    assert persisted is not None
    assert rendered[0]["projection_json"] == persisted["projection_json"]
    with factory() as session:
        audits = (
            session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == first["id"],
                    AuditEvent.event_code == "TOPOLOGY_RUN_RESERVED",
                )
            )
            .scalars()
            .all()
        )
    assert len(audits) == 1


def test_authorized_rerun_requires_reason_and_allocates_next_attempt(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
    rendered: list[dict[str, object]] = []
    runner = GovernedTopologyRunner(factory, storage, rendered.append)
    first = runner.run_official(snapshot_id=ids["snapshot"], **options(ids))

    with pytest.raises(GovernedRunnerError, match="non-empty reason"):
        runner.run_official(snapshot_id=ids["snapshot"], rerun_reason="   ", **options(ids))
    rerun = runner.run_official(
        snapshot_id=ids["snapshot"],
        rerun_reason="Approved deterministic replay",
        **options(ids),
    )

    assert first["attempt_number"] == 0
    assert rerun["attempt_number"] == 1
    assert rerun["rerun_reason"] == "Approved deterministic replay"
    assert rerun["semantic_input_hash"] == first["semantic_input_hash"]
    assert len(rendered) == 2


def test_official_rejects_legacy_snapshot(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage, snapshot_schema="2.0.0")
    runner = GovernedTopologyRunner(factory, storage, lambda _input: None)

    with pytest.raises(GovernedRunnerError, match="v3"):
        runner.run_official(snapshot_id=ids["snapshot"], **options(ids))


def test_official_rejects_tampered_snapshot_before_t1(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        snapshot = session.get(IntakeSnapshot, ids["snapshot"])
        snapshot.canonical_json = snapshot.canonical_json.replace("Synthetic", "Tampered")
        session.commit()
    runner = GovernedTopologyRunner(factory, storage, lambda _input: None)

    with pytest.raises(GovernedRunnerError, match="integrity"):
        runner.run_official(snapshot_id=ids["snapshot"], **options(ids))

    with factory() as session:
        assert TopologyRepository(session).list_generation_runs_for_intake(ids["intake"]) == []


def test_official_rejects_snapshot_row_metadata_mismatch(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        session.get(IntakeSnapshot, ids["snapshot"]).catalog_sha256 = "9" * 64
        session.commit()

    with pytest.raises(GovernedRunnerError, match="metadata"):
        GovernedTopologyRunner(factory, storage, lambda _input: None).run_official(
            snapshot_id=ids["snapshot"], **options(ids)
        )


def test_preview_persists_capture_before_projection_and_render(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        session.query(IntakeSnapshot).filter_by(id=ids["snapshot"]).delete()
        session.get(Intake, ids["intake"]).state = "DRAFT"
        session.commit()
    rendered: list[dict[str, object]] = []
    runner = GovernedTopologyRunner(factory, storage, rendered.append)

    run = runner.run_preview(**options(ids))

    assert rendered[0]["snapshot_id"] is None
    assert rendered[0]["capture_id"] is not None
    with factory() as session:
        stored_run = TopologyRepository(session).get_generation_run(run["id"])
        assert stored_run is not None
        assert stored_run["input_id"] == rendered[0]["input_id"]
        capture_audits = (
            session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == rendered[0]["capture_id"],
                    AuditEvent.event_code == "TOPOLOGY_PREVIEW_CAPTURED",
                )
            )
            .scalars()
            .all()
        )
        assert len(capture_audits) == 1


def test_preview_rejects_identifier_without_normalized_value(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        session.query(IntakeSnapshot).filter_by(id=ids["snapshot"]).delete()
        session.get(Intake, ids["intake"]).state = "DRAFT"
        session.add(
            ApplicationIdentifier(
                id=str(uuid.uuid4()),
                application_id=ids["app"],
                identifier_type="CORRELATION",
                raw_value="COR-001",
                normalized_value="",
                created_at=datetime.now(tz=UTC),
            )
        )
        session.commit()

    with pytest.raises(GovernedRunnerError, match="empty normalized value"):
        GovernedTopologyRunner(factory, storage, lambda _input: None).run_preview(**options(ids))


def test_duplicate_preview_uses_original_capture_and_run(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        session.query(IntakeSnapshot).filter_by(id=ids["snapshot"]).delete()
        session.get(Intake, ids["intake"]).state = "DRAFT"
        session.commit()
    rendered: list[dict[str, object]] = []
    runner = GovernedTopologyRunner(factory, storage, rendered.append)

    first = runner.run_preview(**options(ids))
    second = runner.run_preview(**options(ids))

    assert first["id"] == second["id"]
    assert len(rendered) == 1


def test_overlapping_official_requests_converge_on_one_original_run(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
    rendered: list[str] = []

    def execute() -> str:
        runner = GovernedTopologyRunner(
            factory,
            storage,
            lambda immutable_input: rendered.append(str(immutable_input["run_id"])),
        )
        return str(runner.run_official(snapshot_id=ids["snapshot"], **options(ids))["id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        run_ids = list(executor.map(lambda _index: execute(), range(2)))

    assert len(set(run_ids)) == 1
    assert rendered == [run_ids[0]]
    with factory() as session:
        assert len(TopologyRepository(session).list_generation_runs_for_intake(ids["intake"])) == 1


def test_live_answer_change_after_capture_cannot_change_render_input(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        session.query(IntakeSnapshot).filter_by(id=ids["snapshot"]).delete()
        session.get(Intake, ids["intake"]).state = "DRAFT"
        session.commit()
    rendered: list[str] = []

    def mutate_then_record(immutable_input: dict[str, object]) -> None:
        with factory() as session:
            answer_repository = AnswerRepository(session)
            instance = session.query(AnswerInstance).one()
            revision_id = str(uuid.uuid4())
            answer_repository.add_revision(
                revision_id=revision_id,
                instance_id=str(instance.id),
                revision_number=2,
                response_json={"first": "Changed after capture", "second": "NEW"},
                confirm_state="CONFIRMED",
                authored_at=datetime.now(tz=UTC),
                authored_by_id=ids["actor"],
                response_schema_version="1.0",
            )
            answer_repository.advance_current_pointer(
                str(instance.id),
                revision_id,
                updated_at=datetime.now(tz=UTC),
                value_state="FILLED",
                review_state="CONFIRMED",
            )
            session.commit()
        rendered.append(str(immutable_input["projection_json"]))

    GovernedTopologyRunner(factory, storage, mutate_then_record).run_preview(**options(ids))

    projection = json.loads(rendered[0])
    values = {
        fact["output_key"]: fact["value"]
        for partition in projection["partitions"]
        for fact in partition["facts"]
    }
    assert values["application.name"] == "Synthetic"
    assert values["application.acronym"] == "SYN"


def test_new_preview_after_answer_change_gets_new_semantic_run(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        session.query(IntakeSnapshot).filter_by(id=ids["snapshot"]).delete()
        session.get(Intake, ids["intake"]).state = "DRAFT"
        session.commit()
    runner = GovernedTopologyRunner(factory, storage, lambda _input: None)
    first = runner.run_preview(**options(ids))

    with factory() as session:
        answer_repository = AnswerRepository(session)
        instance = session.query(AnswerInstance).one()
        revision_id = str(uuid.uuid4())
        answer_repository.add_revision(
            revision_id=revision_id,
            instance_id=str(instance.id),
            revision_number=2,
            response_json={"first": "Changed", "second": "NEW"},
            confirm_state="CONFIRMED",
            authored_at=datetime.now(tz=UTC),
            authored_by_id=ids["actor"],
            response_schema_version="1.0",
        )
        answer_repository.advance_current_pointer(
            str(instance.id),
            revision_id,
            updated_at=datetime.now(tz=UTC),
            value_state="FILLED",
            review_state="CONFIRMED",
        )
        session.commit()

    second = runner.run_preview(**options(ids))

    assert first["id"] != second["id"]


def test_no_mutable_answer_sql_after_capture(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
        session.get(Intake, ids["intake"]).state = "DRAFT"
        session.commit()
    statements: list[str] = []
    capture_persisted = False

    def renderer(_input: dict[str, object]) -> None:
        assert capture_persisted

    def tripwire(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal capture_persisted
        statements.append(statement)
        lowered = statement.lower()
        if "insert into topo_captures" in lowered:
            capture_persisted = True
        if capture_persisted and ("ans_instances" in lowered or "ans_revisions" in lowered):
            raise AssertionError("mutable answer query after capture")

    event.listen(tmp_engine, "before_cursor_execute", tripwire)
    try:
        GovernedTopologyRunner(factory, storage, renderer).run_preview(**options(ids))
    finally:
        event.remove(tmp_engine, "before_cursor_execute", tripwire)

    assert capture_persisted
    assert any("ans_instances" in statement.lower() for statement in statements)


def test_official_run_never_queries_mutable_answers(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)

    def tripwire(_conn, _cursor, statement, _parameters, _context, _executemany):
        lowered = statement.lower()
        if "ans_instances" in lowered or "ans_revisions" in lowered:
            raise AssertionError("official run queried mutable answers")

    event.listen(tmp_engine, "before_cursor_execute", tripwire)
    try:
        run = GovernedTopologyRunner(factory, storage, lambda _input: None).run_official(
            snapshot_id=ids["snapshot"], **options(ids)
        )
    finally:
        event.remove(tmp_engine, "before_cursor_execute", tripwire)

    assert run["phase"] == "STORING"


def test_renderer_failure_is_recorded_under_lease(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)

    def fail(_input: dict[str, object]) -> None:
        raise RuntimeError("sensitive synthetic detail")

    with pytest.raises(GovernedRunnerError, match="renderer failed"):
        GovernedTopologyRunner(factory, storage, fail).run_official(
            snapshot_id=ids["snapshot"], **options(ids)
        )

    with factory() as session:
        runs = TopologyRepository(session).list_generation_runs_for_intake(ids["intake"])
    assert len(runs) == 1
    assert runs[0]["phase"] == "FAILED"
    assert runs[0]["readiness_json"] == {"failure_phase": "RENDERING"}
    assert "sensitive synthetic detail" not in (runs[0]["error_message"] or "")


def test_production_renderer_consumes_only_persisted_input(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage)
    renderer = PersistedLabelRenderer(factory, storage)

    run = GovernedTopologyRunner(factory, storage, renderer).run_official(
        snapshot_id=ids["snapshot"], **options(ids)
    )

    assert run["phase"] == "COMPLETED"
    assert renderer.last_output is not None
    assert renderer.last_output.success
    assert b"Synthetic" in renderer.last_output.diagram_bytes


def test_production_renderer_persists_structural_generated_cell(tmp_engine, tmp_path):
    factory = sessionmaker(bind=tmp_engine)
    storage = FilesystemStore(tmp_path / "base-store")
    with factory() as session:
        ids = seed(session, storage, capability=RenderCapability.STRUCTURAL)
    renderer = PersistedLabelRenderer(factory, storage)

    run = GovernedTopologyRunner(factory, storage, renderer).run_official(
        snapshot_id=ids["snapshot"], **options(ids)
    )

    assert run["phase"] == "COMPLETED"
    assert renderer.last_output is not None
    assert b'id="structural-application-label"' in renderer.last_output.diagram_bytes
    assert renderer.last_output.diagnostics.mutation_count >= 2
