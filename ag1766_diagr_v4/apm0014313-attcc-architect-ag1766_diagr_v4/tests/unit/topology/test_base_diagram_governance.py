"""C6.2 migrated-schema base governance integration tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from migration_intake.application.services.base_diagram import (
    BaseDiagramService,
    IncompatibleDiagramError,
    ReviewError,
)
from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    Intake,
)
from migration_intake.persistence.repositories.topology import (
    GenerationConflictError,
    TopologyRepository,
)
from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.topology.contracts import RenderCapability
from migration_intake.topology.profiles import load_profile
from migration_intake.topology.scope import ContextKey, ScopeSelection


def diagram(value: str = "{{APPLICATION_NAME}}") -> bytes:
    return (
        '<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'<mxCell id="2" parent="1" value="{value}"/>'
        "</root></mxGraphModel></diagram></mxfile>"
    ).encode()


@pytest.fixture
def seeded(tmp_engine: object) -> tuple[Session, str, str, str]:
    session = sessionmaker(bind=tmp_engine)()
    now = datetime.now(tz=UTC)
    actor_id, app_id, catalog_id, intake_id = (str(uuid.uuid4()) for _ in range(4))
    session.add(Actor(id=actor_id, display_name="Synthetic actor", created_at=now))
    session.add(Application(id=app_id, state="ACTIVE", display_name="Synthetic", created_at=now, updated_at=now, row_version=1, created_by_id=actor_id))
    session.add(CatalogRelease(id=catalog_id, semantic_version="1.0.0", source_filename="synthetic.csv", source_sha256="a" * 64, compiler_version="1.0.0", pub_state="PUBLISHED", published_at=now, created_at=now))
    session.add(Intake(id=intake_id, application_id=app_id, catalog_id=catalog_id, state="FROZEN", created_at=now, updated_at=now, row_version=1, created_by_id=actor_id))
    session.commit()
    yield session, actor_id, app_id, intake_id
    session.close()


@pytest.fixture
def selection(seeded: tuple[Session, str, str, str]) -> ScopeSelection:
    _, _, app_id, intake_id = seeded
    return ScopeSelection(app_id, intake_id, (ContextKey("PROD", "SITE_A"),), "combined-overview-with-details")


def subject(seeded: tuple[Session, str, str, str], tmp_path: object) -> BaseDiagramService:
    session, _, _, _ = seeded
    return BaseDiagramService(TopologyRepository(session), FilesystemStore(tmp_path / "bases"))


def upload_and_check(service: BaseDiagramService, seeded: tuple[Session, str, str, str], selection: ScopeSelection):
    _, actor_id, app_id, intake_id = seeded
    upload = service.upload_base_diagram(application_id=app_id, intake_id=intake_id, filename="base.xml", diagram_bytes=diagram(), uploaded_by_id=actor_id)
    checked = service.check_compatibility(base_artifact_id=upload.base_artifact_id, profile=load_profile("SYNTHETIC_LABEL_ONLY"), selection=selection, capability=RenderCapability.LABEL_ONLY, partition_views={selection.ordered_contexts[0]: "Overview"}, checked_by_id=actor_id, expected_row_version=1)
    return upload, checked


def test_upload_is_draft_and_compatible_preview_requires_actual_inspection(seeded, selection, tmp_path):
    service = subject(seeded, tmp_path)
    upload, checked = upload_and_check(service, seeded, selection)

    assert upload.state == "DRAFT"
    assert checked.state == "COMPATIBLE"
    assert service.eligible_base(upload.base_artifact_id, official=False)["compatibility_id"] == checked.compatibility_id
    assert len(TopologyRepository(seeded[0]).list_compatibility_for_base(upload.base_artifact_id)) == 1
    with pytest.raises(ReviewError):
        service.eligible_base(upload.base_artifact_id, official=True)


def test_missing_required_slot_cannot_be_compatible(seeded, selection, tmp_path):
    service = subject(seeded, tmp_path)
    _, actor_id, app_id, intake_id = seeded
    upload = service.upload_base_diagram(application_id=app_id, intake_id=intake_id, filename="base.xml", diagram_bytes=diagram("Static"), uploaded_by_id=actor_id)

    with pytest.raises(IncompatibleDiagramError):
        service.check_compatibility(base_artifact_id=upload.base_artifact_id, profile=load_profile("SYNTHETIC_LABEL_ONLY"), selection=selection, capability=RenderCapability.LABEL_ONLY, partition_views={selection.ordered_contexts[0]: "Overview"}, checked_by_id=actor_id, expected_row_version=1)


def test_approval_rechecks_trusted_profile_and_exact_pins(seeded, selection, tmp_path):
    service = subject(seeded, tmp_path)
    upload, checked = upload_and_check(service, seeded, selection)
    _, actor_id, _, _ = seeded
    approved = service.approve_base_diagram(base_artifact_id=upload.base_artifact_id, selection=selection, capability=RenderCapability.LABEL_ONLY, partition_views={selection.ordered_contexts[0]: "Overview"}, approved_by_id=actor_id, rationale="synthetic review", expected_row_version=checked.row_version)

    assert approved.state == "APPROVED"
    assert service.eligible_base(upload.base_artifact_id, official=True)["authority"] == "OFFICIAL_SNAPSHOT"


def test_stale_review_cas_is_not_swallowed(seeded, selection, tmp_path):
    service = subject(seeded, tmp_path)
    upload, checked = upload_and_check(service, seeded, selection)
    _, actor_id, _, _ = seeded

    with pytest.raises(GenerationConflictError):
        service.approve_base_diagram(base_artifact_id=upload.base_artifact_id, selection=selection, capability=RenderCapability.LABEL_ONLY, partition_views={selection.ordered_contexts[0]: "Overview"}, approved_by_id=actor_id, rationale="stale", expected_row_version=1)
    assert checked.row_version == 2


def test_superseded_base_cannot_be_official(seeded, selection, tmp_path):
    service = subject(seeded, tmp_path)
    upload, checked = upload_and_check(service, seeded, selection)
    _, actor_id, _, _ = seeded
    approved = service.approve_base_diagram(base_artifact_id=upload.base_artifact_id, selection=selection, capability=RenderCapability.LABEL_ONLY, partition_views={selection.ordered_contexts[0]: "Overview"}, approved_by_id=actor_id, rationale="approved", expected_row_version=checked.row_version)
    service.supersede_base_diagram(base_artifact_id=upload.base_artifact_id, superseded_by_id=actor_id, rationale="replacement", expected_row_version=approved.row_version)

    with pytest.raises(ReviewError):
        service.eligible_base(upload.base_artifact_id, official=True)
