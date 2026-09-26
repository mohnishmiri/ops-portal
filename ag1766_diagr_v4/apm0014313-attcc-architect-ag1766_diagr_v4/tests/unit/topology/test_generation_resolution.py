"""Tests for standard-template generation resolution behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.services.topology_generation import TopologyGenerationService
from migration_intake.persistence.database import create_engine_from_url
from migration_intake.persistence.models import Actor, Application, Base, CatalogRelease, Intake
from migration_intake.persistence.repositories.templates import TemplateRepository


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_from_url(
        f"sqlite:///{tmp_path / 'generation-resolution.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    actor_id = "00000000-0000-0000-0000-000000000001"
    app_id = str(uuid.uuid4())
    intake_id = str(uuid.uuid4())
    catalog_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)

    with factory() as session:
        session.add(Actor(id=actor_id, display_name="Topology Admin", created_at=now))
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Template Resolution App",
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
                source_filename="catalog.csv",
                source_sha256="a" * 64,
                compiler_version="1.0",
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
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()

    return factory, intake_id, actor_id


def test_generate_from_standard_uses_resolved_template_source(
    session_factory, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, intake_id, actor_id = session_factory
    service = TopologyGenerationService(factory, storage_root=Path(tmp_path) / "evidence")
    fake_template = (
        b'<mxfile><diagram name="Without LBs"><mxGraphModel><root><mxCell id="db"/></root></mxGraphModel></diagram></mxfile>'
    )
    release_id = "11111111-1111-1111-1111-111111111111"
    with factory() as session:
        TemplateRepository(session).add_release(
            release_id=release_id,
            template_version="1.8",
            source_filename="outpost_v1.8.drawio",
            source_sha256="f" * 64,
            content_address="ff/" + "f" * 64,
            size_bytes=100,
            tab_count=4,
            variant_manifest=[],
            compiler_version="1.0.0",
            compiler_report={"diagnostics": []},
            pub_state="PUBLISHED",
            published_at=datetime.now(tz=UTC),
            published_by_id=actor_id,
            created_at=datetime.now(tz=UTC),
        )
        session.commit()

    monkeypatch.setattr(
        "migration_intake.application.services.topology_generation.resolve_template",
        lambda variant, session_factory, storage: (fake_template, release_id),
    )
    monkeypatch.setattr(
        service,
        "_generate_diagram",
        lambda *_args, **_kwargs: (fake_template, {"issues": []}, {"nodes": [], "connections": []}),
    )
    monkeypatch.setattr(
        service,
        "_generate_report",
        lambda *_args, **_kwargs: b"<html></html>",
    )

    run = service.generate_from_standard_template(
        intake_id=intake_id,
        variant="basic",
        actor=ActorContext(actor_id=actor_id),
    )

    assert run["status"] == "READY_FOR_REVIEW"
    bases = service.list_base_artifacts(intake_id)
    base = next(item for item in bases if item["id"] == run["base_artifact_id"])
    assert base.get("template_release_id") == release_id
