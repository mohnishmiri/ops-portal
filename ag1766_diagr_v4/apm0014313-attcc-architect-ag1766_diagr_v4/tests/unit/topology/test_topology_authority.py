"""TP06 immutable topology authority publication tests."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from migration_intake.application.services.topology_authority import (
    TopologyAuthorityError,
    TopologyAuthorityService,
)
from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_resources import (
    TopologyResourceLink,
    TopologyResourceLinkRevision,
)
from migration_intake.persistence.models_snapshots import IntakeSnapshot
from migration_intake.persistence.repositories.interfaces import InterfaceRepository
from migration_intake.persistence.repositories.resources import ResourceRepository


def _seed(factory: sessionmaker) -> dict[str, str]:
    now = datetime.now(UTC)
    ids = [str(uuid.uuid4()) for _ in range(8)]
    actor, app, catalog, intake, section, question, instance, revision = ids
    with factory() as session:
        session.add(Actor(id=actor, display_name="Synthetic", created_at=now))
        session.add(Application(id=app, state="ACTIVE", display_name="Synthetic", created_at=now, updated_at=now, row_version=1, interface_epoch=1, created_by_id=actor))
        session.add(CatalogRelease(id=catalog, semantic_version="1.0.0", source_filename="synthetic", source_sha256=__import__("hashlib").sha256(catalog.encode()).hexdigest(), compiler_version="1.0.0", catalog_hash=__import__("hashlib").sha256((catalog + "compiled").encode()).hexdigest(), pub_state="PUBLISHED", published_at=now, created_at=now))
        session.add(Intake(id=intake, application_id=app, catalog_id=catalog, state="FROZEN", created_at=now, updated_at=now, row_version=1, content_epoch=1, created_by_id=actor))
        session.add(CatalogSection(id=section, release_id=catalog, section_code="CTL", display_name="Control", display_order=1))
        session.flush()
        session.add(CatalogQuestion(id=question, section_id=section, question_code="CTL-002", question_text="Name", response_type="TEXT_PAIR", required_level="REQUIRED", collection_mode="MANUAL", display_order=1))
        session.flush()
        session.add(AnswerInstance(id=instance, intake_id=intake, question_id=question, created_at=now, current_rev_id=None, applicability="APPLICABLE", value_state="ANSWERED", review_state="CONFIRMED", updated_at=now, row_version=1))
        session.flush()
        session.add(AnswerRevision(id=revision, instance_id=instance, revision_number=1, response_json={"first": "Synthetic", "second": "SYN"}, confirm_state="CONFIRMED", authored_at=now, authored_by_id=actor, response_schema_version="1.0"))
        session.flush()
        session.get(AnswerInstance, instance).current_rev_id = revision
        session.commit()
    return {"actor": actor, "app": app, "catalog": catalog, "intake": intake}


def _interface_fields(identifier: str) -> dict[str, str]:
    return {
        "migrating_app_correlation_id": "APP",
        "interface_correlation_id": identifier,
        "interface_app_acronym": identifier,
        "interface_system_location": "AWS",
        "data_traffic_direction": "Inbound",
        "target_protocol": "HTTPS",
        "future_port": "443",
        "end_point_name": "secret-free-text-endpoint",
        "interface_contact": "private@example.test",
        "notes": "private notes",
    }


def test_interface_reorder_is_hash_stable_and_sensitive_fields_are_absent(tmp_engine) -> None:
    factory = sessionmaker(bind=tmp_engine)
    context = _seed(factory)
    now = datetime.now(UTC)
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    with factory() as session:
        repo = InterfaceRepository(session)
        for record_id, identifier in reversed(list(zip(ids, ("IF-1", "IF-2"), strict=True))):
            repo.create_record(record_id=record_id, application_id=context["app"], fields=_interface_fields(identifier), origin="IMPORT", created_at=now, created_by_id=context["actor"])
        session.commit()
    first = TopologyAuthorityService(factory).publish_v3(context["intake"], context["actor"])
    document = json.loads(first["canonical_json"])
    assert [row["id"] for row in document["interface_register"]["rows"]] == sorted(ids)
    assert "private@example.test" not in first["canonical_json"]
    assert "private notes" not in first["canonical_json"]
    assert "secret-free-text-endpoint" not in first["canonical_json"]
    assert TopologyAuthorityService(factory).publish_v3(context["intake"], context["actor"])["sha256_hex"] == first["sha256_hex"]


def test_confirmed_active_resources_links_and_provenance_are_published(tmp_engine) -> None:
    factory = sessionmaker(bind=tmp_engine)
    context = _seed(factory)
    now = datetime.now(UTC)
    source_id, target_id, retired_id = (str(uuid.uuid4()) for _ in range(3))
    with factory() as session:
        repo = ResourceRepository(session)
        repo.create_resource(source_id, context["intake"], "source", "PLACEMENT", "TARGET", None, None, None, None, {"name": "source"}, "CONFIRMED", context["actor"], now, ["evidence:source"])
        repo.create_resource(target_id, context["intake"], "target", "PLACEMENT", "TARGET", None, None, None, None, {"name": "target"}, "CONFIRMED", context["actor"], now, ["evidence:target"])
        repo.create_resource(retired_id, context["intake"], "retired", "PLACEMENT", "TARGET", None, None, None, None, {"name": "retired"}, "CONFIRMED", context["actor"], now, ["evidence:retired"])
        repo.retire_resource(retired_id, context["actor"], now, "retired", 1)
        link_id, link_revision_id = str(uuid.uuid4()), str(uuid.uuid4())
        session.add(TopologyResourceLink(id=link_id, intake_id=context["intake"], relationship_type="COMMUNICATES_WITH", source_resource_id=source_id, target_resource_id=target_id, current_revision_id=link_revision_id, revision_number=1, row_version=1, link_state="ACTIVE", created_at=now, updated_at=now, created_by=context["actor"]))
        session.add(TopologyResourceLinkRevision(id=link_revision_id, link_id=link_id, revision_number=1, review_state="CONFIRMED", provenance_references=["evidence:link"], authored_at=now, authored_by=context["actor"]))
        session.commit()
    snapshot = TopologyAuthorityService(factory).publish_v3(context["intake"], context["actor"])
    document = json.loads(snapshot["canonical_json"])
    assert {item["id"] for item in document["resources"]} == {source_id, target_id}
    assert document["resources"][0]["revision"]["provenance_references"]
    assert document["relationships"][0]["revision"]["provenance_references"] == ["evidence:link"]


def test_interface_mutation_changes_new_authority_without_changing_old_bytes(tmp_engine) -> None:
    factory = sessionmaker(bind=tmp_engine)
    first_context = _seed(factory)
    now = datetime.now(UTC)
    with factory() as session:
        InterfaceRepository(session).create_record(record_id=str(uuid.uuid4()), application_id=first_context["app"], fields=_interface_fields("IF-1"), origin="MANUAL", created_at=now, created_by_id=first_context["actor"])
        session.commit()
    first = TopologyAuthorityService(factory).publish_v3(first_context["intake"], first_context["actor"])
    first_bytes = first["canonical_json"]
    second_context = _seed(factory)
    with factory() as session:
        repo = InterfaceRepository(session)
        repo.create_record(record_id=str(uuid.uuid4()), application_id=second_context["app"], fields=_interface_fields("IF-1"), origin="MANUAL", created_at=now, created_by_id=second_context["actor"])
        repo.create_record(record_id=str(uuid.uuid4()), application_id=second_context["app"], fields=_interface_fields("IF-2"), origin="MANUAL", created_at=now, created_by_id=second_context["actor"])
        session.commit()
    second = TopologyAuthorityService(factory).publish_v3(second_context["intake"], second_context["actor"])
    assert second["sha256_hex"] != first["sha256_hex"]
    with factory() as session:
        assert session.get(IntakeSnapshot, first["id"]).canonical_json == first_bytes


def test_candidates_unconfirmed_and_retired_facts_are_excluded(tmp_engine) -> None:
    factory = sessionmaker(bind=tmp_engine)
    context = _seed(factory)
    now = datetime.now(UTC)
    with factory() as session:
        repo = ResourceRepository(session)
        unconfirmed_id = str(uuid.uuid4())
        repo.create_resource(unconfirmed_id, context["intake"], "unconfirmed", "PLACEMENT", "TARGET", None, None, None, None, {"private": "unconfirmed-secret"}, "PROPOSED", context["actor"], now)
        retired_id = str(uuid.uuid4())
        repo.create_resource(retired_id, context["intake"], "retired", "PLACEMENT", "TARGET", None, None, None, None, {"private": "retired-secret"}, "CONFIRMED", context["actor"], now)
        repo.retire_resource(retired_id, context["actor"], now, "retired", 1)
        session.commit()
    snapshot = TopologyAuthorityService(factory).publish_v3(context["intake"], context["actor"])
    assert "candidate-secret" not in snapshot["canonical_json"]
    assert "unconfirmed-secret" not in snapshot["canonical_json"]
    assert "retired-secret" not in snapshot["canonical_json"]


def test_old_authority_is_immutable_and_legacy_snapshot_cannot_be_relabelled(tmp_engine) -> None:
    factory = sessionmaker(bind=tmp_engine)
    context = _seed(factory)
    now = datetime.now(UTC)
    with factory() as session:
        session.add(IntakeSnapshot(id=str(uuid.uuid4()), intake_id=context["intake"], catalog_id=context["catalog"], schema_version="2.0.0", catalog_sha256="a" * 64, canonical_json='{"schema_version":"2.0.0"}', sha256_hex="c" * 64, created_at=now, created_by_id=context["actor"]))
        session.commit()
    with pytest.raises(TopologyAuthorityError, match="cannot be relabeled"):
        TopologyAuthorityService(factory).publish_v3(context["intake"], context["actor"])
    with factory() as session:
        snapshot = session.query(IntakeSnapshot).filter_by(intake_id=context["intake"]).one()
        assert snapshot.schema_version == "2.0.0"
        assert snapshot.canonical_json == '{"schema_version":"2.0.0"}'
