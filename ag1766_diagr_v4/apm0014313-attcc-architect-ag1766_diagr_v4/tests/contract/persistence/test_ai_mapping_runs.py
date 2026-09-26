"""
Contract tests for AIMappingRunRepository (PAI-5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from migration_intake.persistence.models import Actor, Application, CatalogRelease, Intake
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.repositories.ai_mapping_runs import AIMappingRunRepository

_NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)


def _uid() -> str:
    return str(uuid.uuid4())


def _seed_prereqs(engine) -> tuple[str, str, str, str]:
    actor_id = _uid()
    app_id = _uid()
    intake_id = _uid()
    evidence_id = _uid()
    cat_id = _uid()

    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="AI Mapper", attuid="ai1", created_at=_NOW))
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="AI App",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="catalog.csv",
                source_sha256="a" * 64,
                compiler_version="1.0.0",
                pub_state="PUBLISHED",
                created_at=_NOW,
            )
        )
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=cat_id,
                state="DRAFT",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.add(
            EvidenceItem(
                id=evidence_id,
                application_id=app_id,
                intake_id=intake_id,
                storage_key="evidence/key",
                sha256_hex="b" * 64,
                size_bytes=123,
                media_type="text/plain",
                original_filename="sample.txt",
                state="ACTIVE",
                created_at=_NOW,
                created_by_id=actor_id,
            )
        )
        session.commit()
    return actor_id, app_id, intake_id, evidence_id


def test_add_and_get_run(tmp_engine) -> None:
    actor_id, app_id, intake_id, evidence_id = _seed_prereqs(tmp_engine)
    run_id = _uid()

    with Session(tmp_engine) as session:
        repo = AIMappingRunRepository(session)
        created = repo.add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=evidence_id,
            provider_id="openai_compatible",
            profile_id="synthetic-local",
            model_id="test-model",
            prompt_template_version="v1.0",
            classification="SYNTHETIC",
            fragment_count=2,
            started_at=_NOW,
            created_by_id=actor_id,
            created_at=_NOW,
        )
        session.commit()

    assert created["id"] == run_id
    assert created["status"] == "PENDING"
    assert created["candidate_count"] == 0

    with Session(tmp_engine) as session:
        fetched = AIMappingRunRepository(session).get_run(run_id)
    assert fetched is not None
    assert fetched["provider_id"] == "openai_compatible"
    assert fetched["classification"] == "SYNTHETIC"


def test_mark_running_then_completed(tmp_engine) -> None:
    actor_id, app_id, intake_id, evidence_id = _seed_prereqs(tmp_engine)
    run_id = _uid()

    with Session(tmp_engine) as session:
        repo = AIMappingRunRepository(session)
        repo.add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=evidence_id,
            provider_id="openai_compatible",
            profile_id="synthetic-local",
            model_id="test-model",
            prompt_template_version="v1.0",
            classification="SYNTHETIC",
            fragment_count=1,
            started_at=_NOW,
            created_by_id=actor_id,
            created_at=_NOW,
        )
        assert repo.mark_running(run_id) is True
        assert repo.mark_completed(
            run_id,
            request_hash="c" * 64,
            response_hash="d" * 64,
            attempt_count=2,
            candidate_count=3,
            finding_count=1,
            finished_at=_NOW + timedelta(seconds=5),
            metrics_json={"latency_bucket": "<=1s"},
        ) is True
        session.commit()

    with Session(tmp_engine) as session:
        run = AIMappingRunRepository(session).get_run(run_id)
    assert run is not None
    assert run["status"] == "COMPLETED"
    assert run["candidate_count"] == 3
    assert run["finding_count"] == 1


def test_mark_failed_from_pending(tmp_engine) -> None:
    actor_id, app_id, intake_id, evidence_id = _seed_prereqs(tmp_engine)
    run_id = _uid()

    with Session(tmp_engine) as session:
        repo = AIMappingRunRepository(session)
        repo.add_run(
            run_id=run_id,
            application_id=app_id,
            intake_id=intake_id,
            evidence_item_id=evidence_id,
            provider_id="openai_compatible",
            profile_id="synthetic-local",
            model_id="test-model",
            prompt_template_version="v1.0",
            classification="SYNTHETIC",
            fragment_count=1,
            started_at=_NOW,
            created_by_id=actor_id,
            created_at=_NOW,
        )
        ok = repo.mark_failed(
            run_id,
            attempt_count=1,
            failure_category="TRANSPORT",
            failure_detail_redacted="timeout",
            finished_at=_NOW + timedelta(seconds=2),
            metrics_json={"attempts": 1},
        )
        session.commit()
    assert ok is True

    with Session(tmp_engine) as session:
        run = AIMappingRunRepository(session).get_run(run_id)
    assert run is not None
    assert run["status"] == "FAILED"
    assert run["failure_category"] == "TRANSPORT"
    assert run["failure_detail_redacted"] == "timeout"
