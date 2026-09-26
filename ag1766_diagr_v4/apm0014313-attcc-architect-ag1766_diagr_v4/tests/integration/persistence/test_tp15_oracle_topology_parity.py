"""TP15 non-destructive Oracle topology persistence parity."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.database import configure_oracle_client, create_engine_from_url
from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake
from migration_intake.persistence.models_topology import GenerationRun, TopologyBaseArtifact
from migration_intake.persistence.repositories.topology import GenerationConflictError, TopologyRepository

pytestmark = pytest.mark.oracle


@pytest.fixture(scope="module")
def oracle_factory():
    url = os.environ.get("DATABASE_URL") or os.environ.get("ORACLE_TEST_URL")
    if not url:
        pytest.skip("Oracle certification URL is not configured")
    client = os.environ.get("AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR") or os.environ.get("ORACLE_CLIENT_LIB_DIR")
    configure_oracle_client(Path(client) if client else None)
    engine = create_engine_from_url(url)
    with engine.connect() as connection:
        assert connection.dialect.name == "oracle"
    yield sessionmaker(bind=engine)
    engine.dispose()


def test_oracle_topology_constraints_are_present(oracle_factory) -> None:
    inspector = inspect(oracle_factory.kw["bind"])
    names = {item["name"] for item in inspector.get_unique_constraints("gen_runs")}
    assert "uq_grun_attempt" in names
    artifact_names = {item["name"] for item in inspector.get_unique_constraints("gen_artifacts")}
    assert "uq_gart_type" in artifact_names
    foreign_keys = {item["name"] for item in inspector.get_foreign_keys("gen_runs")}
    assert {"fk_gnrn_app", "fk_gnrn_int", "fk_gnrn_bas"} <= foreign_keys


def test_oracle_run_cas_and_lease_fencing(oracle_factory) -> None:
    now = datetime.now(UTC)
    ids = [str(uuid.uuid4()) for _ in range(6)]
    actor_id, app_id, catalog_id, intake_id, base_id, run_id = ids
    with oracle_factory() as session:
        session.add(Actor(id=actor_id, display_name="TP15 Oracle", created_at=now))
        session.add(Application(id=app_id, state="ACTIVE", display_name="TP15", created_at=now, updated_at=now, row_version=1, created_by_id=actor_id))
        session.add(CatalogRelease(id=catalog_id, semantic_version="tp15-" + catalog_id[:8], source_filename="tp15.csv", source_sha256=uuid.uuid4().hex * 2, compiler_version="1", catalog_hash=uuid.uuid4().hex * 2, pub_state="PUBLISHED", published_at=now, created_at=now))
        session.add(Intake(id=intake_id, application_id=app_id, catalog_id=catalog_id, state="FROZEN", created_at=now, updated_at=now, row_version=1, content_epoch=1, created_by_id=actor_id))
        session.flush()
        session.add(TopologyBaseArtifact(id=base_id, application_id=app_id, intake_id=intake_id, filename="tp15.drawio", mime_type="application/xml", size_bytes=1, sha256_hex="c" * 64, content_address="cc/" + "c" * 64, uploaded_by_id=actor_id, uploaded_at=now, created_at=now, review_state="APPROVED", lifecycle="ACTIVE", row_version=1))
        session.flush()
        session.add(GenerationRun(id=run_id, application_id=app_id, intake_id=intake_id, base_artifact_id=base_id, base_sha256="c" * 64, mode="DRAFT_PREVIEW", capability="LABEL_ONLY", authority="DRAFT_PREVIEW", phase="PENDING", status="PENDING", row_version=1, semantic_input_hash=uuid.uuid4().hex * 2, attempt_number=0, requested_by_id=actor_id, requested_at=now, created_at=now))
        session.commit()
        repository = TopologyRepository(session)
        claimed = repository.claim_generation_run(run_id=run_id, expected_row_version=1, lease_token="tp15-lease", lease_expires_at=now + timedelta(minutes=5))
        session.commit()
        assert claimed["phase"] == "RENDERING"
        with pytest.raises(GenerationConflictError):
            repository.transition_leased_generation_phase(run_id=run_id, expected_row_version=claimed["row_version"], expected_phase="RENDERING", new_phase="STORING", lease_token="stale-lease")
        session.rollback()
        session.delete(session.get(GenerationRun, run_id))
        session.delete(session.get(TopologyBaseArtifact, base_id))
        session.delete(session.get(Intake, intake_id))
        session.delete(session.get(Application, app_id))
        session.delete(session.get(CatalogRelease, catalog_id))
        session.delete(session.get(Actor, actor_id))
        session.commit()
