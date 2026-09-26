"""
Application summary service (UX-4a).

Provides aggregate read models for the application list and workspace views
without N+1 queries.  All queries use SQLAlchemy 2.x select() style.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

_TERMINAL_INTAKE_STATES: tuple[str, ...] = ("FROZEN", "CANCELLED", "SUPERSEDED")


def get_application_list_stats(
    session_factory: sessionmaker,
    app_ids: list[str],
) -> dict[str, dict]:
    """
    Return per-app stats for the application list view in three bounded queries.

    Args:
        session_factory: SQLAlchemy sessionmaker bound to the application DB.
        app_ids: Application IDs whose stats are needed.

    Returns:
        Mapping of app_id → {
            evidence_count: int,
            pending_proposal_count: int,
            has_open_intake: bool,
            open_intake_id: str | None,
        }
    """
    from migration_intake.persistence.models import Intake
    from migration_intake.persistence.models_candidates import Candidate
    from migration_intake.persistence.models_evidence import EvidenceItem

    if not app_ids:
        return {}

    result: dict[str, dict] = {
        app_id: {
            "evidence_count": 0,
            "pending_proposal_count": 0,
            "has_open_intake": False,
            "open_intake_id": None,
        }
        for app_id in app_ids
    }

    session: Session = session_factory()
    try:
        # Query 1: first open intake per application (first created wins).
        intake_rows = session.execute(
            select(
                Intake.application_id.label("app_id"),
                Intake.id.label("intake_id"),
            )
            .where(
                Intake.application_id.in_(app_ids),
                Intake.state.not_in(_TERMINAL_INTAKE_STATES),
            )
            .order_by(Intake.application_id.asc(), Intake.created_at.asc())
        ).mappings().all()

        open_intake_map: dict[str, str] = {}
        for row in intake_rows:
            app_id = str(row["app_id"])
            if app_id not in open_intake_map:  # first-created wins
                open_intake_map[app_id] = str(row["intake_id"])

        for app_id, intake_id in open_intake_map.items():
            if app_id in result:
                result[app_id]["has_open_intake"] = True
                result[app_id]["open_intake_id"] = intake_id

        # Query 2: ACTIVE evidence count per application.
        for row in session.execute(
            select(
                EvidenceItem.application_id.label("app_id"),
                func.count().label("cnt"),
            )
            .where(
                EvidenceItem.application_id.in_(app_ids),
                EvidenceItem.state == "ACTIVE",
            )
            .group_by(EvidenceItem.application_id)
        ).mappings().all():
            app_id = str(row["app_id"])
            if app_id in result:
                result[app_id]["evidence_count"] = int(row["cnt"])

        # Query 3: PROPOSED candidate count per app (open intakes only).
        open_intake_ids = list(open_intake_map.values())
        if open_intake_ids:
            for row in session.execute(
                select(
                    Candidate.application_id.label("app_id"),
                    func.count().label("cnt"),
                )
                .where(
                    Candidate.application_id.in_(app_ids),
                    Candidate.intake_id.in_(open_intake_ids),
                    Candidate.state == "PROPOSED",
                )
                .group_by(Candidate.application_id)
            ).mappings().all():
                app_id = str(row["app_id"])
                if app_id in result:
                    result[app_id]["pending_proposal_count"] = int(row["cnt"])

        return result
    finally:
        session.close()


def get_workspace_summary(
    session_factory: sessionmaker,
    app_id: str,
) -> dict | None:
    """
    Return workspace dict extended with hub_href, proposal_count, readiness_state.

    Builds on the existing ApplicationQueryService.get_application_workspace
    (which already includes evidence_count) and adds:
      - hub_href: "/applications/{app_id}/intakes/{intake_id}" for the open intake
      - proposal_count: PROPOSED candidate count for the open intake
      - readiness_state: open intake state (proxy for readiness)

    Returns None if the application does not exist.
    """
    from migration_intake.application.queries import ApplicationQueryService
    from migration_intake.persistence.models_candidates import Candidate
    from migration_intake.persistence.repositories.interfaces import InterfaceRepository

    query_service = ApplicationQueryService(session_factory)
    workspace = query_service.get_application_workspace(app_id)
    if workspace is None:
        return None

    open_intake = workspace.get("open_intake")
    hub_href: str | None = None
    proposal_count = 0
    interface_count = 0
    interface_proposal_count = 0
    readiness_state: str | None = None

    if open_intake:
        intake_id = str(open_intake["id"])
        hub_href = f"/applications/{app_id}/intakes/{intake_id}"
        readiness_state = open_intake.get("state")

        session: Session = session_factory()
        try:
            proposal_count = int(
                session.execute(
                    select(func.count())
                    .select_from(Candidate)
                    .where(
                        Candidate.intake_id == intake_id,
                        Candidate.state == "PROPOSED",
                    )
                ).scalar()
                or 0
            )
            interface_count = len(
                InterfaceRepository(session).list_records_for_application(app_id, state="ACTIVE")
            )
            interface_proposal_count = int(
                session.execute(
                    select(func.count())
                    .select_from(Candidate)
                    .where(
                        Candidate.application_id == app_id,
                        Candidate.intake_id == intake_id,
                        Candidate.target_kind == "INTERFACE_REGISTER",
                        Candidate.state == "PROPOSED",
                    )
                ).scalar()
                or 0
            )
        finally:
            session.close()

    return {
        **workspace,
        "hub_href": hub_href,
        "proposal_count": proposal_count,
        "interface_count": interface_count,
        "interface_proposal_count": interface_proposal_count,
        "readiness_state": readiness_state,
    }
