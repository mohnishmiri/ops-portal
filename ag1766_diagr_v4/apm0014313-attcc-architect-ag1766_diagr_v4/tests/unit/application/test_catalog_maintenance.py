"""Tests for explicit catalog maintenance and draft repinning."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.application.services.catalog_maintenance import (
    CatalogMaintenanceError,
    CatalogMaintenanceService,
)
from migration_intake.persistence.models import (
    Actor,
    Application,
    CatalogRelease,
    Intake,
)
from migration_intake.persistence.naming import Base
import migration_intake.persistence.models  # noqa: F401
import migration_intake.persistence.models_candidates  # noqa: F401
import migration_intake.persistence.models_evidence  # noqa: F401
import migration_intake.persistence.models_imports  # noqa: F401
import migration_intake.persistence.models_snapshots  # noqa: F401


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'maintenance.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def maintenance_context(session_factory):
    actor_id = str(uuid.uuid4())
    application_id = str(uuid.uuid4())
    intake_id = str(uuid.uuid4())
    old_catalog_id = str(uuid.uuid4())
    new_catalog_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)

    with session_factory() as session:
        session.add(Actor(id=actor_id, display_name="Synthetic", created_at=now))
        session.add(
            Application(
                id=application_id,
                state="ACTIVE",
                display_name="Synthetic Application",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.add_all(
            [
                CatalogRelease(
                    id=old_catalog_id,
                    semantic_version="0.2.0",
                    source_filename="old.csv",
                    source_sha256="a" * 64,
                    catalog_hash="b" * 64,
                    compiler_version="1.0.0",
                    pub_state="PUBLISHED",
                    published_at=now,
                    created_at=now,
                ),
                CatalogRelease(
                    id=new_catalog_id,
                    semantic_version="1.0.0",
                    source_filename="new.csv",
                    source_sha256="c" * 64,
                    catalog_hash="d" * 64,
                    compiler_version="1.0.0",
                    pub_state="PUBLISHED",
                    published_at=now,
                    created_at=now,
                ),
                Intake(
                    id=intake_id,
                    application_id=application_id,
                    catalog_id=old_catalog_id,
                    state="DRAFT",
                    created_at=now,
                    updated_at=now,
                    row_version=1,
                    created_by_id=actor_id,
                ),
            ]
        )
        session.commit()

    return {
        "factory": session_factory,
        "actor": ActorContext(actor_id=actor_id, display_name="Synthetic"),
        "intake_id": intake_id,
        "old_catalog_id": old_catalog_id,
        "new_catalog_id": new_catalog_id,
    }


def test_repin_empty_draft_dry_run_does_not_write(maintenance_context):
    context = maintenance_context
    result = CatalogMaintenanceService(context["factory"]).repin_empty_draft(
        intake_id=context["intake_id"],
        new_catalog_id=context["new_catalog_id"],
        expected_row_version=1,
        actor=context["actor"],
        apply=False,
    )

    assert result.dry_run is True
    with context["factory"]() as session:
        row = session.execute(
            text("SELECT catalog_id, row_version FROM intakes WHERE id = :id"),
            {"id": context["intake_id"]},
        ).one()
    assert str(row.catalog_id) == context["old_catalog_id"]
    assert row.row_version == 1


def test_repin_empty_draft_apply_is_cas_and_audited(maintenance_context):
    context = maintenance_context
    result = CatalogMaintenanceService(context["factory"]).repin_empty_draft(
        intake_id=context["intake_id"],
        new_catalog_id=context["new_catalog_id"],
        expected_row_version=1,
        actor=context["actor"],
        apply=True,
    )

    assert result.new_row_version == 2
    with context["factory"]() as session:
        row = session.execute(
            text("SELECT catalog_id, row_version FROM intakes WHERE id = :id"),
            {"id": context["intake_id"]},
        ).one()
        audit = session.execute(
            text(
                "SELECT event_code FROM audit_events "
                "WHERE entity_type = 'intake' AND entity_id = :id"
            ),
            {"id": context["intake_id"]},
        ).one()
    assert str(row.catalog_id) == context["new_catalog_id"]
    assert row.row_version == 2
    assert audit.event_code == "INTAKE_CATALOG_REPINNED"


def test_repin_rejects_stale_version(maintenance_context):
    context = maintenance_context
    with pytest.raises(ConcurrencyConflictError):
        CatalogMaintenanceService(context["factory"]).repin_empty_draft(
            intake_id=context["intake_id"],
            new_catalog_id=context["new_catalog_id"],
            expected_row_version=2,
            actor=context["actor"],
            apply=True,
        )


def test_repin_rejects_candidate_dependency(maintenance_context):
    context = maintenance_context
    now = datetime.now(tz=UTC)
    candidate_id = str(uuid.uuid4())
    with context["factory"]() as session:
        # Candidate dependency is tested through the table existence and query
        # contract in the service; no client payload is needed here.
        session.add(
            __import__("migration_intake.persistence.models_candidates", fromlist=["Candidate"]).Candidate(
                id=candidate_id,
                import_run_id=str(uuid.uuid4()),
                application_id=str(uuid.uuid4()),
                intake_id=context["intake_id"],
                evidence_item_id=str(uuid.uuid4()),
                target_kind="QUESTION",
                target_key="SYN-001",
                origin="synthetic",
                extractor_version="1",
                contract_version="1",
                raw_value_json={"value": "synthetic"},
                state="PROPOSED",
                row_version=1,
                created_at=now,
            )
        )
        session.commit()

    with pytest.raises(CatalogMaintenanceError, match="candidates"):
        CatalogMaintenanceService(context["factory"]).repin_empty_draft(
            intake_id=context["intake_id"],
            new_catalog_id=context["new_catalog_id"],
            expected_row_version=1,
            actor=context["actor"],
            apply=True,
        )