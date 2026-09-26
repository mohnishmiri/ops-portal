"""
Unit tests for application_summary.py (UX-4a).

Tests verify get_application_list_stats and get_workspace_summary return
correct aggregates from seeded SQLite data.  Synthetic fixtures only
(AGENTS.md — never use client evidence).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

# Side-effect: register all ORM tables in Base.metadata before
# conftest creates the engine.
import migration_intake.persistence.models_evidence  # noqa: F401
import migration_intake.persistence.models_imports  # noqa: F401
import migration_intake.persistence.models_candidates  # noqa: F401

from migration_intake.persistence.models import (
    Actor,
    Application,
    ApplicationIdentifier,
    CatalogRelease,
    Intake,
)
from migration_intake.persistence.models_candidates import Candidate
from migration_intake.persistence.models_evidence import EvidenceItem
from migration_intake.persistence.models_imports import ImportRun

from migration_intake.application.services.application_summary import (
    get_application_list_stats,
    get_workspace_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _sha256() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _seed_actor(engine) -> str:
    aid = _uuid()
    with Session(engine) as s:
        s.add(Actor(id=aid, display_name="Test Actor", created_at=_NOW))
        s.commit()
    return aid


def _seed_catalog(engine) -> str:
    cat_id = _uuid()
    with Session(engine) as s:
        s.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="1.0.0",
                source_filename="catalog.yaml",
                source_sha256=_sha256(),
                compiler_version="1.0",
                pub_state="PUBLISHED",
                created_at=_NOW,
            )
        )
        s.commit()
    return cat_id


def _seed_application(engine, actor_id: str, display_name: str = "Test App") -> str:
    app_id = _uuid()
    with Session(engine) as s:
        s.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name=display_name,
                created_at=_NOW,
                updated_at=_NOW,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        s.commit()
    return app_id


def _seed_identifier(engine, app_id: str, id_type: str, value: str) -> None:
    with Session(engine) as s:
        s.add(
            ApplicationIdentifier(
                id=_uuid(),
                application_id=app_id,
                identifier_type=id_type,
                raw_value=value,
                created_at=_NOW,
            )
        )
        s.commit()


def _seed_intake(
    engine, app_id: str, catalog_id: str, actor_id: str, state: str = "DRAFT"
) -> str:
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


def _seed_evidence(engine, app_id: str, actor_id: str, intake_id: str, count: int = 1) -> None:
    with Session(engine) as s:
        for _ in range(count):
            ev_id = _uuid()
            s.add(
                EvidenceItem(
                    id=ev_id,
                    application_id=app_id,
                    intake_id=intake_id,
                    storage_key=f"uploads/{app_id}/{ev_id}.xlsx",
                    sha256_hex=_sha256(),
                    size_bytes=1024,
                    media_type="application/octet-stream",
                    original_filename="synthetic.xlsx",
                    state="ACTIVE",
                    created_at=_NOW,
                    created_by_id=actor_id,
                )
            )
        s.commit()


def _seed_import_run(engine, app_id: str, actor_id: str, intake_id: str) -> tuple[str, str]:
    """Create an evidence item + import run and return (run_id, evidence_item_id)."""
    ev_id = _uuid()
    run_id = _uuid()
    with Session(engine) as s:
        ev = EvidenceItem(
            id=ev_id,
            application_id=app_id,
            intake_id=intake_id,
            storage_key=f"run-ev/{ev_id}.xlsx",
            sha256_hex=_sha256(),
            size_bytes=1,
            media_type="application/octet-stream",
            original_filename="run.xlsx",
            state="ACTIVE",
            created_at=_NOW,
            created_by_id=actor_id,
        )
        s.add(ev)
        s.flush()  # ensure evidence_item_id is valid before import run
        s.add(
            ImportRun(
                id=run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=ev_id,
                contract_name="synthetic_v1",
                parser_version="1.0",
                state="COMPLETED",
                total_candidates=0,
                total_findings=0,
                created_at=_NOW,
                created_by_id=actor_id,
            )
        )
        s.commit()
    return run_id, ev_id


def _seed_candidate(
    engine,
    app_id: str,
    intake_id: str,
    import_run_id: str,
    evidence_item_id: str,
    state: str = "PROPOSED",
) -> str:
    cand_id = _uuid()
    with Session(engine) as s:
        s.add(
            Candidate(
                id=cand_id,
                import_run_id=import_run_id,
                application_id=app_id,
                intake_id=intake_id,
                evidence_item_id=evidence_item_id,
                target_kind="QUESTION",
                target_key="Q-001",
                origin="synthetic",
                extractor_version="1.0",
                contract_version="1.0",
                raw_value_json={"text": "synthetic value"},
                scope_json={"scope": "APPLICATION"},
                state=state,
                row_version=1,
                created_at=_NOW,
            )
        )
        s.commit()
    return cand_id


# ---------------------------------------------------------------------------
# get_application_list_stats
# ---------------------------------------------------------------------------


class TestGetApplicationListStats:

    def test_empty_app_ids_returns_empty_dict(self, session_factory) -> None:
        result = get_application_list_stats(session_factory, [])
        assert result == {}

    def test_app_with_no_intake_returns_zero_counts(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)

        result = get_application_list_stats(session_factory, [app_id])

        assert result[app_id]["evidence_count"] == 0
        assert result[app_id]["pending_proposal_count"] == 0
        assert result[app_id]["has_open_intake"] is False
        assert result[app_id]["open_intake_id"] is None

    def test_open_intake_detected(self, tmp_engine, session_factory) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        cat_id = _seed_catalog(tmp_engine)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        result = get_application_list_stats(session_factory, [app_id])

        assert result[app_id]["has_open_intake"] is True
        assert result[app_id]["open_intake_id"] == intake_id

    def test_terminal_intake_not_counted_as_open(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        cat_id = _seed_catalog(tmp_engine)
        _seed_intake(tmp_engine, app_id, cat_id, actor_id, state="FROZEN")

        result = get_application_list_stats(session_factory, [app_id])

        assert result[app_id]["has_open_intake"] is False

    def test_evidence_count_matches_active_files(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        cat_id = _seed_catalog(tmp_engine)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)
        _seed_evidence(tmp_engine, app_id, actor_id, intake_id, count=3)

        result = get_application_list_stats(session_factory, [app_id])

        assert result[app_id]["evidence_count"] == 3

    def test_proposal_count_matches_proposed_candidates(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        cat_id = _seed_catalog(tmp_engine)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)
        run_id, ev_id = _seed_import_run(tmp_engine, app_id, actor_id, intake_id)
        _seed_candidate(tmp_engine, app_id, intake_id, run_id, ev_id, state="PROPOSED")
        _seed_candidate(tmp_engine, app_id, intake_id, run_id, ev_id, state="PROPOSED")
        _seed_candidate(tmp_engine, app_id, intake_id, run_id, ev_id, state="ACCEPTED")

        result = get_application_list_stats(session_factory, [app_id])

        # Only PROPOSED candidates count.
        assert result[app_id]["pending_proposal_count"] == 2

    def test_multiple_apps_stats_are_independent(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        cat_id = _seed_catalog(tmp_engine)

        app1 = _seed_application(tmp_engine, actor_id, "App One")
        int1 = _seed_intake(tmp_engine, app1, cat_id, actor_id)
        _seed_evidence(tmp_engine, app1, actor_id, int1, count=2)

        app2 = _seed_application(tmp_engine, actor_id, "App Two")
        # app2 has no intake or evidence

        result = get_application_list_stats(session_factory, [app1, app2])

        assert result[app1]["evidence_count"] == 2
        assert result[app2]["evidence_count"] == 0
        assert result[app1]["has_open_intake"] is True
        assert result[app2]["has_open_intake"] is False

    def test_app_id_not_in_list_is_absent_from_result(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        other_id = _uuid()

        result = get_application_list_stats(session_factory, [app_id])

        assert other_id not in result


# ---------------------------------------------------------------------------
# get_workspace_summary
# ---------------------------------------------------------------------------


class TestGetWorkspaceSummary:

    def test_returns_none_for_missing_app(self, session_factory) -> None:
        result = get_workspace_summary(session_factory, _uuid())
        assert result is None

    def test_returns_workspace_dict(self, tmp_engine, session_factory) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id, "Summary App")

        result = get_workspace_summary(session_factory, app_id)

        assert result is not None
        assert result["id"] == app_id
        assert result["display_name"] == "Summary App"

    def test_hub_href_is_none_when_no_intake(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)

        result = get_workspace_summary(session_factory, app_id)

        assert result is not None
        assert result["hub_href"] is None
        assert result["proposal_count"] == 0

    def test_hub_href_format_when_intake_exists(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        cat_id = _seed_catalog(tmp_engine)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        result = get_workspace_summary(session_factory, app_id)

        assert result is not None
        assert result["hub_href"] == f"/applications/{app_id}/intakes/{intake_id}"

    def test_proposal_count_from_open_intake(
        self, tmp_engine, session_factory
    ) -> None:
        actor_id = _seed_actor(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        cat_id = _seed_catalog(tmp_engine)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)
        run_id, ev_id = _seed_import_run(tmp_engine, app_id, actor_id, intake_id)
        _seed_candidate(tmp_engine, app_id, intake_id, run_id, ev_id, state="PROPOSED")
        _seed_candidate(tmp_engine, app_id, intake_id, run_id, ev_id, state="ACCEPTED")

        result = get_workspace_summary(session_factory, app_id)

        assert result is not None
        assert result["proposal_count"] == 1  # only PROPOSED
