"""
Unit tests for ApplicationQueryService — A03 read-model query services.

TDD RED → GREEN:
  Tests are written first and fail (AttributeError / ImportError) until
  ApplicationQueryService is added to queries.py.

Fixtures ``tmp_engine`` and ``session_factory`` come from conftest.py.

Side-effect imports at module level register ALL ORM tables in Base.metadata
BEFORE conftest.tmp_engine calls Base.metadata.create_all(), so every table
(including evidence_items and import_runs) is present in the schema.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

# Side-effect: register evidence + import tables in Base.metadata before
# conftest.tmp_engine calls create_all().
import migration_intake.persistence.models_evidence  # noqa: F401
import migration_intake.persistence.models_imports  # noqa: F401

# --- ORM models needed for seeding ------------------------------------------
from migration_intake.persistence.models import (
    Actor,
    Application,
    ApplicationIdentifier,
    AnswerInstance,
    AnswerRevision,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun

# --- class under test -------------------------------------------------------
from migration_intake.application.queries import ApplicationQueryService


# ===========================================================================
# Seed helpers
# ===========================================================================

_NOW = datetime.now(tz=timezone.utc)
_SHA256 = "a" * 64


def _actor_id() -> str:
    return str(uuid.uuid4())


def _uuid() -> str:
    return str(uuid.uuid4())


def _seed_actor(engine, actor_id: str | None = None) -> str:
    """Insert an Actor row and return its id."""
    aid = actor_id or _uuid()
    with Session(engine) as s:
        s.add(Actor(id=aid, display_name="Test Actor", created_at=_NOW))
        s.commit()
    return aid


def _seed_catalog(engine) -> str:
    """Insert a PUBLISHED CatalogRelease row and return its id."""
    cat_id = _uuid()
    sha = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    with Session(engine) as s:
        s.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="catalog.yaml",
                source_sha256=sha,
                compiler_version="1.0",
                pub_state="PUBLISHED",
                created_at=_NOW,
            )
        )
        s.commit()
    return cat_id


def _seed_application(engine, actor_id: str, state: str = "ACTIVE") -> str:
    """Insert an Application row and return its id."""
    app_id = _uuid()
    with Session(engine) as s:
        s.add(
            Application(
                id=app_id,
                state=state,
                display_name=f"App {app_id[:8]}",
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        s.commit()
    return app_id


def _seed_intake(
    engine,
    app_id: str,
    catalog_id: str,
    actor_id: str,
    state: str = "DRAFT",
) -> str:
    """Insert an Intake row and return its id."""
    intake_id = _uuid()
    with Session(engine) as s:
        s.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=catalog_id,
                state=state,
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        s.commit()
    return intake_id


def _seed_section(engine, catalog_id: str, section_code: str = "SEC-001") -> str:
    """Insert a CatalogSection row and return its id."""
    section_id = _uuid()
    with Session(engine) as s:
        s.add(
            CatalogSection(
                id=section_id,
                release_id=catalog_id,
                section_code=section_code,
                display_name=f"Section {section_code}",
                display_order=1,
            )
        )
        s.commit()
    return section_id


def _seed_question(
    engine,
    section_id: str,
    question_code: str = "Q-001",
    display_order: int = 1,
) -> str:
    """Insert a CatalogQuestion row and return its id."""
    q_id = _uuid()
    with Session(engine) as s:
        s.add(
            CatalogQuestion(
                id=q_id,
                section_id=section_id,
                question_code=question_code,
                question_text=f"Question {question_code}?",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="MANUAL",
                display_order=display_order,
                is_active=True,
            )
        )
        s.commit()
    return q_id


def _seed_answer(
    engine,
    intake_id: str,
    question_id: str,
    actor_id: str,
    response_json: dict | None = None,
) -> tuple[str, str]:
    """
    Insert an AnswerInstance + AnswerRevision (the circular FK pattern).
    Returns (instance_id, revision_id).
    """
    instance_id = _uuid()
    revision_id = _uuid()
    if response_json is None:
        response_json = {"value": "test answer"}

    # Step 1: insert instance with current_rev_id=NULL
    with Session(engine) as s:
        s.add(
            AnswerInstance(
                id=instance_id,
                intake_id=intake_id,
                question_id=question_id,
                created_at=_NOW,
                current_rev_id=None,
                applicability="APPLICABLE",
                value_state="EMPTY",
                review_state="UNREVIEWED",
                updated_at=_NOW,
                row_version=1,
            )
        )
        s.commit()

    # Step 2: insert revision
    with Session(engine) as s:
        s.add(
            AnswerRevision(
                id=revision_id,
                instance_id=instance_id,
                revision_number=1,
                response_json=response_json,
                confirm_state="PENDING",
                authored_at=_NOW,
                authored_by_id=actor_id,
            )
        )
        s.commit()

    # Step 3: update instance to point to revision
    with Session(engine) as s:
        inst = s.get(AnswerInstance, instance_id)
        inst.current_rev_id = revision_id
        s.commit()

    return instance_id, revision_id


def _seed_evidence(
    engine,
    app_id: str,
    actor_id: str,
    intake_id: str | None = None,
    state: str = "ACTIVE",
    count: int = 1,
) -> list[str]:
    """Insert EvidenceItem rows and return their ids."""
    ids = []
    for i in range(count):
        ev_id = _uuid()
        sha = hashlib.sha256(f"{ev_id}{i}".encode()).hexdigest()
        storage_key = f"uploads/{app_id}/{ev_id}.xlsx"
        with Session(engine) as s:
            s.add(
                EvidenceItem(
                    id=ev_id,
                    application_id=app_id,
                    intake_id=intake_id,
                    storage_key=storage_key,
                    sha256_hex=sha,
                    size_bytes=1024,
                    media_type="application/octet-stream",
                    original_filename="file.xlsx",
                    state=state,
                    created_at=_NOW,
                    created_by_id=actor_id,
                )
            )
            s.commit()
        ids.append(ev_id)
    return ids


def _seed_import_run(
    engine,
    app_id: str,
    actor_id: str,
    intake_id: str | None = None,
    state: str = "COMPLETED",
    total_candidates: int = 10,
    total_findings: int = 2,
) -> str:
    """Insert an ImportRun row and return its id."""
    run_id = _uuid()
    with Session(engine) as s:
        s.add(
            ImportRun(
                id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=None,
                contract_name="waveutil_v1",
                parser_version="1.0.0",
                state=state,
                total_candidates=total_candidates,
                total_findings=total_findings,
                created_at=_NOW,
                created_by_id=actor_id,
            )
        )
        s.commit()
    return run_id


# ===========================================================================
# list_applications tests
# ===========================================================================


class TestListApplications:
    def test_list_applications_empty_returns_empty_list(
        self, tmp_engine, session_factory
    ) -> None:
        """No applications → empty list returned."""
        svc = ApplicationQueryService(session_factory)
        result = svc.list_applications()
        assert result == []

    def test_list_applications_returns_id_and_display_name(
        self, tmp_engine, session_factory
    ) -> None:
        """One application → list with correct id, display_name keys."""
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.list_applications()

        assert len(result) == 1
        row = result[0]
        assert row["id"] == app_id
        assert isinstance(row["display_name"], str)
        assert "state" in row
        assert "created_at" in row

    def test_list_applications_state_filter(
        self, tmp_engine, session_factory
    ) -> None:
        """Two apps (ACTIVE + ARCHIVED) → filter ACTIVE returns exactly 1."""
        actor_id = _seed_actor(tmp_engine)
        active_id = _seed_application(tmp_engine, actor_id, state="ACTIVE")
        _seed_application(tmp_engine, actor_id, state="ARCHIVED")

        svc = ApplicationQueryService(session_factory)
        result = svc.list_applications(state_filter="ACTIVE")

        assert len(result) == 1
        assert result[0]["id"] == active_id

    def test_list_applications_pagination(
        self, tmp_engine, session_factory
    ) -> None:
        """3 apps, limit=2/offset=0 → 2 results; limit=2/offset=2 → 1 result."""
        actor_id = _seed_actor(tmp_engine)
        _seed_application(tmp_engine, actor_id)
        _seed_application(tmp_engine, actor_id)
        _seed_application(tmp_engine, actor_id)

        svc = ApplicationQueryService(session_factory)
        page1 = svc.list_applications(limit=2, offset=0)
        page2 = svc.list_applications(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 1

    def test_list_applications_includes_open_intake_id(
        self, tmp_engine, session_factory
    ) -> None:
        """App with an open DRAFT intake → open_intake_id is set."""
        actor_id = _seed_actor(tmp_engine)
        cat_id = _seed_catalog(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id, state="DRAFT")

        svc = ApplicationQueryService(session_factory)
        result = svc.list_applications()

        assert len(result) == 1
        assert result[0]["open_intake_id"] == intake_id

    def test_list_applications_no_intake_shows_null(
        self, tmp_engine, session_factory
    ) -> None:
        """App with no intake → open_intake_id is None."""
        actor_id = _seed_actor(tmp_engine)
        _seed_application(tmp_engine, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.list_applications()

        assert len(result) == 1
        assert result[0]["open_intake_id"] is None


# ===========================================================================
# get_application_workspace tests
# ===========================================================================


class TestGetApplicationWorkspace:
    def test_get_workspace_returns_application_data(
        self, tmp_engine, session_factory
    ) -> None:
        """Valid application id → dict with id, display_name, state."""
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_application_workspace(app_id)

        assert result is not None
        assert result["id"] == app_id
        assert isinstance(result["display_name"], str)
        assert result["state"] == "ACTIVE"

    def test_get_workspace_includes_identifiers(
        self, tmp_engine, session_factory
    ) -> None:
        """App with 2 identifiers → identifiers list has 2 items with type/raw_value."""
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)

        with Session(tmp_engine) as s:
            s.add(
                ApplicationIdentifier(
                    id=_uuid(),
                    application_id=app_id,
                    identifier_type="ITAP",
                    raw_value="APP-001",
                    normalized_value="app-001",
                    created_at=_NOW,
                )
            )
            s.add(
                ApplicationIdentifier(
                    id=_uuid(),
                    application_id=app_id,
                    identifier_type="MOTS",
                    raw_value="MOTS-999",
                    normalized_value="mots-999",
                    created_at=_NOW,
                )
            )
            s.commit()

        svc = ApplicationQueryService(session_factory)
        result = svc.get_application_workspace(app_id)

        assert result is not None
        idents = result["identifiers"]
        assert len(idents) == 2
        types = {i["type"] for i in idents}
        assert "ITAP" in types
        assert "MOTS" in types
        for i in idents:
            assert "type" in i
            assert "raw_value" in i

    def test_get_workspace_returns_none_for_unknown_id(
        self, tmp_engine, session_factory
    ) -> None:
        """Nonexistent application id → None."""
        svc = ApplicationQueryService(session_factory)
        result = svc.get_application_workspace(_uuid())
        assert result is None

    def test_get_workspace_includes_open_intake(
        self, tmp_engine, session_factory
    ) -> None:
        """App with open DRAFT intake → open_intake dict with id, state, catalog_id."""
        actor_id = _seed_actor(tmp_engine)
        cat_id = _seed_catalog(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id, state="DRAFT")

        svc = ApplicationQueryService(session_factory)
        result = svc.get_application_workspace(app_id)

        assert result is not None
        oi = result["open_intake"]
        assert oi is not None
        assert oi["id"] == intake_id
        assert oi["state"] == "DRAFT"
        assert oi["catalog_id"] == cat_id

    def test_get_workspace_no_intake_shows_null(
        self, tmp_engine, session_factory
    ) -> None:
        """App without any intake → open_intake is None."""
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_application_workspace(app_id)

        assert result is not None
        assert result["open_intake"] is None

    def test_get_workspace_evidence_count(
        self, tmp_engine, session_factory
    ) -> None:
        """2 ACTIVE evidence items → evidence_count == 2."""
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        _seed_evidence(tmp_engine, app_id, actor_id, count=2)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_application_workspace(app_id)

        assert result is not None
        assert result["evidence_count"] == 2


# ===========================================================================
# get_questionnaire_section tests
# ===========================================================================


class TestGetQuestionnaireSection:
    def _setup_section(
        self, engine, section_code: str = "SEC-001"
    ) -> tuple[str, str, str, str]:
        """
        Seed a full intake + catalog section + 2 questions.
        Returns (actor_id, intake_id, section_id, (q1_id, q2_id)).
        """
        actor_id = _seed_actor(engine)
        cat_id = _seed_catalog(engine)
        app_id = _seed_application(engine, actor_id)
        intake_id = _seed_intake(engine, app_id, cat_id, actor_id)
        section_id = _seed_section(engine, cat_id, section_code=section_code)
        return actor_id, cat_id, intake_id, section_id

    def test_get_section_returns_questions(
        self, tmp_engine, session_factory
    ) -> None:
        """Section with 2 questions → questions list has 2 items."""
        actor_id, cat_id, intake_id, section_id = self._setup_section(tmp_engine)
        _seed_question(tmp_engine, section_id, "Q-001", display_order=1)
        _seed_question(tmp_engine, section_id, "Q-002", display_order=2)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_section(intake_id, "SEC-001")

        assert result is not None
        assert result["section_code"] == "SEC-001"
        assert isinstance(result["display_name"], str)
        assert len(result["questions"]) == 2
        q = result["questions"][0]
        assert "question_code" in q
        assert "question_text" in q
        assert "response_type" in q
        assert "required_level" in q
        assert "current_answer" in q

    def test_get_section_includes_current_answer(
        self, tmp_engine, session_factory
    ) -> None:
        """Question with an answered instance → current_answer dict is present."""
        actor_id, cat_id, intake_id, section_id = self._setup_section(tmp_engine)
        q_id = _seed_question(tmp_engine, section_id, "Q-001")
        _seed_answer(tmp_engine, intake_id, q_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_section(intake_id, "SEC-001")

        assert result is not None
        assert len(result["questions"]) == 1
        ca = result["questions"][0]["current_answer"]
        assert ca is not None
        assert "instance_id" in ca
        assert "revision_number" in ca
        assert ca["revision_number"] == 1
        assert "response_json" in ca
        assert "confirm_state" in ca
        assert "authored_at" in ca

    def test_get_section_no_answer_shows_null(
        self, tmp_engine, session_factory
    ) -> None:
        """Question without an answer instance → current_answer is None."""
        _, _, intake_id, section_id = self._setup_section(tmp_engine)
        _seed_question(tmp_engine, section_id, "Q-001")

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_section(intake_id, "SEC-001")

        assert result is not None
        assert result["questions"][0]["current_answer"] is None

    def test_get_section_unknown_code_returns_none(
        self, tmp_engine, session_factory
    ) -> None:
        """Unknown section_code for valid intake → None."""
        _, _, intake_id, _ = self._setup_section(tmp_engine)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_questionnaire_section(intake_id, "DOES-NOT-EXIST")

        assert result is None


# ===========================================================================
# get_import_run_summary tests
# ===========================================================================


class TestGetImportRunSummary:
    def test_get_import_run_summary_empty(
        self, tmp_engine, session_factory
    ) -> None:
        """No import runs for intake → empty list."""
        actor_id = _seed_actor(tmp_engine)
        cat_id = _seed_catalog(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        svc = ApplicationQueryService(session_factory)
        result = svc.get_import_run_summary(intake_id)

        assert result == []

    def test_get_import_run_summary_returns_run_data(
        self, tmp_engine, session_factory
    ) -> None:
        """One import run → list with run_id, state, total_candidates, total_findings, created_at."""
        actor_id = _seed_actor(tmp_engine)
        cat_id = _seed_catalog(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)
        run_id = _seed_import_run(
            tmp_engine,
            app_id,
            actor_id,
            intake_id=intake_id,
            state="COMPLETED",
            total_candidates=42,
            total_findings=7,
        )

        svc = ApplicationQueryService(session_factory)
        result = svc.get_import_run_summary(intake_id)

        assert len(result) == 1
        run = result[0]
        assert run["run_id"] == run_id
        assert run["state"] == "COMPLETED"
        assert run["total_candidates"] == 42
        assert run["total_findings"] == 7
        assert isinstance(run["created_at"], str)
