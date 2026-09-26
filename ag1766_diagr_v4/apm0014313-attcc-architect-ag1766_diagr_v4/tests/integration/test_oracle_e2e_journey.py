"""End-to-end Oracle journey test (O06C) using current repository contracts."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from migration_intake.persistence.database import (
    configure_oracle_client,
    create_engine_from_url,
    create_session_factory,
)
from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    ApplicationIdentifier,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_candidates import AnswerEvidenceLink, Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun
from migration_intake.persistence.models_snapshots import IntakeSnapshot
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.candidates import CandidateRepository
from migration_intake.persistence.repositories.evidence import EvidenceRepository
from migration_intake.persistence.repositories.imports import ImportRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.persistence.repositories.snapshots import SnapshotRepository

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.oracle


@pytest.fixture
def oracle_engine() -> Engine:
    """Create an Oracle engine after explicit Thick-mode initialization."""
    url = os.environ.get("DATABASE_URL") or os.environ.get("ORACLE_TEST_URL")
    if not url:
        pytest.skip("Oracle certification URL is not configured")
    client_dir = os.environ.get("AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR") or os.environ.get(
        "ORACLE_CLIENT_LIB_DIR"
    )
    configure_oracle_client(Path(client_dir) if client_dir else None)
    engine = create_engine_from_url(url)
    with engine.connect() as connection:
        username = str(connection.execute(text("SELECT USER FROM dual")).scalar_one())
        assert username.upper() not in {"SYS", "SYSTEM"}
    try:
        yield engine
    finally:
        engine.dispose()


def test_oracle_end_to_end_journey(oracle_engine: Engine) -> None:
    """Verify the canonical Oracle persistence journey with deterministic cleanup."""
    session_factory = create_session_factory(oracle_engine)
    now = datetime.now(UTC)

    ids: dict[str, str] = {
        "actor": str(uuid4()),
        "application": str(uuid4()),
        "catalog": str(uuid4()),
        "section": str(uuid4()),
        "question": str(uuid4()),
        "intake": str(uuid4()),
        "instance": str(uuid4()),
        "revision_1": str(uuid4()),
        "revision_2": str(uuid4()),
        "evidence": str(uuid4()),
        "import_run": str(uuid4()),
        "snapshot": str(uuid4()),
    }
    optional_ids: dict[str, str | None] = {
        "identifier": None,
        "candidate": None,
        "link": None,
    }

    try:
        with Session(oracle_engine) as session:
            version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version == "0022"

        with session_factory() as session:
            session.add(Actor(id=ids["actor"], display_name="TP15 Oracle E2E", created_at=now))

            app_repo = ApplicationRepository(session)
            app_repo.add(
                actor_id=ids["actor"],
                display_name="TP15 Oracle E2E App",
                state="DRAFT",
                created_at=now,
                application_id=ids["application"],
            )
            unique_identifier_value = f"tp15-{ids['application'][:12]}"
            optional_ids["identifier"] = app_repo.add_identifier(
                application_id=ids["application"],
                identifier_type="aws_account_id",
                raw_value=unique_identifier_value,
                normalized_value=unique_identifier_value,
                created_at=now,
            )

            session.add(
                CatalogRelease(
                    id=ids["catalog"],
                    semantic_version=f"tp15-{ids['catalog'][:8]}",
                    source_filename="tp15-oracle-e2e.csv",
                    source_sha256=uuid4().hex * 2,
                    compiler_version="1.0.0",
                    pub_state="PUBLISHED",
                    published_at=now,
                    catalog_hash=uuid4().hex * 2,
                    created_at=now,
                )
            )
            session.add(
                CatalogSection(
                    id=ids["section"],
                    release_id=ids["catalog"],
                    section_code="E2E_CORE",
                    display_name="E2E Core",
                    display_order=1,
                )
            )
            # Ensure parent catalog rows are persisted before question/intake inserts.
            session.flush()
            session.add(
                CatalogQuestion(
                    id=ids["question"],
                    section_id=ids["section"],
                    question_code="APP_HOSTING_MODEL",
                    question_text="What is the hosting model?",
                    response_type="TEXT",
                    required_level="REQUIRED",
                    collection_mode="MANUAL",
                    condition_ast=None,
                    display_order=1,
                    is_active=True,
                    response_schema_version="1.0.0",
                )
            )
            session.flush()

            IntakeRepository(session).add(
                intake_id=ids["intake"],
                application_id=ids["application"],
                catalog_id=ids["catalog"],
                state="DRAFT",
                created_by_id=ids["actor"],
                created_at=now,
            )

            answer_repo = AnswerRepository(session)
            answer_repo.add_instance(
                instance_id=ids["instance"],
                intake_id=ids["intake"],
                question_id=ids["question"],
                created_at=now,
            )
            answer_repo.add_revision(
                revision_id=ids["revision_1"],
                instance_id=ids["instance"],
                revision_number=1,
                response_json={"value": "Initial answer"},
                confirm_state="DRAFT",
                authored_at=now,
                authored_by_id=ids["actor"],
                response_schema_version="1.0.0",
            )
            answer_repo.advance_current_pointer(
                instance_id=ids["instance"],
                revision_id=ids["revision_1"],
                updated_at=now,
                value_state="POPULATED",
                review_state="UNREVIEWED",
            )
            answer_repo.add_revision(
                revision_id=ids["revision_2"],
                instance_id=ids["instance"],
                revision_number=2,
                response_json={"value": "Updated answer"},
                confirm_state="CONFIRMED",
                authored_at=now,
                authored_by_id=ids["actor"],
                response_schema_version="1.0.0",
                change_reason="integration update",
            )
            answer_repo.advance_current_pointer(
                instance_id=ids["instance"],
                revision_id=ids["revision_2"],
                updated_at=now,
                value_state="POPULATED",
                review_state="UNREVIEWED",
            )

            evidence_repo = EvidenceRepository(session)
            evidence_repo.add(
                evidence_id=ids["evidence"],
                application_id=ids["application"],
                intake_id=ids["intake"],
                storage_key=f"tp15/{ids['evidence']}.txt",
                sha256_hex="a" * 64,
                size_bytes=512,
                media_type="text/plain",
                original_filename="tp15-e2e.txt",
                created_at=now,
                created_by_id=ids["actor"],
            )

            import_repo = ImportRepository(session)
            import_repo.add_run(
                run_id=ids["import_run"],
                application_id=ids["application"],
                intake_id=ids["intake"],
                evidence_item_id=ids["evidence"],
                contract_name="tp15-e2e",
                parser_version="1.0.0",
                created_at=now,
                created_by_id=ids["actor"],
            )
            import_repo.update_run_state(
                ids["import_run"],
                new_state="COMPLETED",
                total_sheets=1,
                total_candidates=1,
                total_findings=0,
                completed_at=now,
                identity_decision="ACCEPTED",
            )

            candidate_repo = CandidateRepository(session)
            candidate = candidate_repo.create_candidate(
                import_run_id=ids["import_run"],
                application_id=ids["application"],
                intake_id=ids["intake"],
                evidence_item_id=ids["evidence"],
                target_kind="QUESTION",
                target_key="APP_HOSTING_MODEL",
                origin="ORACLE_E2E_TEST",
                extractor_version="1.0.0",
                contract_version="1.0.0",
                raw_value_json={"value": "Updated answer"},
                normalized_value_json={"value": "Updated answer"},
                source_locator={"sheet": "Questions", "row": 1},
                response_schema_version="1.0.0",
                confidence=1.0,
            )
            optional_ids["candidate"] = str(candidate.id)
            session.flush()
            updated = candidate_repo.compare_and_set_state(
                candidate_id=str(candidate.id),
                expected_row_version=1,
                expected_state="PROPOSED",
                new_state="ACCEPTED",
                decided_by_id=ids["actor"],
                decided_at=now,
                decision_rationale="TP15 Oracle E2E acceptance",
                accepted_value_json={"value": "Updated answer"},
            )
            assert updated

            link = candidate_repo.create_evidence_link(
                revision_id=ids["revision_2"],
                evidence_item_id=ids["evidence"],
                link_type="IMPORT_ACCEPTANCE",
                candidate_id=str(candidate.id),
                source_locator={"sheet": "Questions", "row": 1},
            )
            optional_ids["link"] = str(link.id)

            snapshot_payload = {
                "schema_version": "3.0.0",
                "application": {"id": ids["application"], "name": "TP15 Oracle E2E App"},
                "intake": {"id": ids["intake"], "state": "DRAFT"},
                "answers": [
                    {
                        "question_id": ids["question"],
                        "response_json": {"value": "Updated answer"},
                    }
                ],
            }
            SnapshotRepository(session).create_snapshot(
                snapshot_id=ids["snapshot"],
                intake_id=ids["intake"],
                catalog_id=ids["catalog"],
                schema_version="3.0.0",
                catalog_sha256="b" * 64,
                canonical_json=json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")),
                sha256_hex="c" * 64,
                created_at=now,
                created_by_id=ids["actor"],
            )
            session.commit()

        with session_factory() as session:
            app = ApplicationRepository(session).get(ids["application"])
            assert app is not None
            assert app["display_name"] == "TP15 Oracle E2E App"

            intake = IntakeRepository(session).get(ids["intake"])
            assert intake is not None
            assert intake["state"] == "DRAFT"

            current = AnswerRepository(session).get_current_revision(ids["instance"])
            assert current is not None
            assert current["revision_number"] == 2
            assert current["confirm_state"] == "CONFIRMED"
            assert current["response_json"]["value"] == "Updated answer"

            evidence = EvidenceRepository(session).get(ids["evidence"])
            assert evidence is not None
            assert evidence["storage_key"].startswith("tp15/")

            run = ImportRepository(session).get_run(ids["import_run"])
            assert run is not None
            assert run["state"] == "COMPLETED"
            assert run["total_candidates"] == 1

            candidate_row = CandidateRepository(session).get_by_id(optional_ids["candidate"] or "")
            assert candidate_row is not None
            assert candidate_row.state == "ACCEPTED"
            assert candidate_row.row_version == 2

            provenance = AnswerRepository(session).get_provenance_references_for_revision(
                ids["revision_2"]
            )
            assert ids["evidence"] in provenance

            snapshot = SnapshotRepository(session).get_by_id(ids["snapshot"])
            assert snapshot is not None
            assert snapshot["sha256_hex"] == "c" * 64
            assert snapshot["catalog_id"] == ids["catalog"]
    finally:
        with session_factory() as session:
            session.execute(
                text("UPDATE ans_instances SET current_rev_id = NULL WHERE id = :instance_id"),
                {"instance_id": ids["instance"]},
            )
            for model, value in (
                (AnswerEvidenceLink, optional_ids["link"]),
                (Candidate, optional_ids["candidate"]),
                (ImportRun, ids["import_run"]),
                (EvidenceItem, ids["evidence"]),
                (IntakeSnapshot, ids["snapshot"]),
                (AnswerRevision, ids["revision_2"]),
                (AnswerRevision, ids["revision_1"]),
                (AnswerInstance, ids["instance"]),
                (Intake, ids["intake"]),
                (CatalogQuestion, ids["question"]),
                (CatalogSection, ids["section"]),
                (CatalogRelease, ids["catalog"]),
                (ApplicationIdentifier, optional_ids["identifier"]),
                (Application, ids["application"]),
                (Actor, ids["actor"]),
            ):
                if value:
                    session.execute(delete(model).where(model.id == value))
            session.commit()
