"""
Application and Intake service commands — A01.

Architecture rules applied here (sections 23–25.1, 27.1–27.2, 28):

- Receives validated commands; does NOT parse HTTP or read env vars.
- Loads state through repositories inside a UoW.
- Invokes domain policies (state checks, duplicate checks).
- Commits through UoW.
- Returns detached plain dicts — no ORM entities leave this module.
- Does NOT swallow concurrency/integrity errors.

Audit events use ``event_code`` (the ORM column name).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.orm import sessionmaker

from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
    UpdateApplicationIdentityCommand,
)
from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import (
    ApplicationNotActiveError,
    ApplicationNotFoundError,
    CatalogNotPublishedError,
    ConcurrencyConflictError,
    DuplicateIdentifierError,
    OpenIntakeExistsError,
)
from migration_intake.persistence.models import Actor, ApplicationIdentifier, AuditEvent
from migration_intake.persistence.unit_of_work import UnitOfWork, uow_context

# Open intake states — an application may not have more than one.
_OPEN_INTAKE_STATES: frozenset[str] = frozenset(
    {
        "DRAFT",
        "COLLECTING",
        "IN_REVIEW",
        "CHANGES_REQUESTED",
        "READY_TO_FREEZE",
    }
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    """Strip leading/trailing whitespace and collapse internal runs."""
    return " ".join(name.split())


def _ensure_actor(uow: UnitOfWork, actor: ActorContext, now: datetime) -> None:
    """
    Insert the actor row if it does not already exist.

    Uses a check-then-insert pattern within the current session/transaction.
    Callers must not commit between the check and the insert.
    """
    from sqlalchemy import select

    stmt = select(Actor).where(Actor.id == actor.actor_id)
    existing = uow._session.execute(stmt).scalar_one_or_none()
    if existing is None:
        actor_row = Actor(
            id=actor.actor_id,
            display_name=actor.display_name or "Unknown",
            attuid=None,
            created_at=now,
        )
        uow._session.add(actor_row)
        uow._session.flush()


def _write_audit(
    uow: UnitOfWork,
    actor: ActorContext,
    event_code: str,
    entity_type: str,
    entity_id: str,
    now: datetime,
) -> None:
    """
    Append an immutable audit event row to the current transaction.

    ``entity_id`` must be a valid UUID string; the ORM column is PortableUUID.
    ``event_code`` maps to the ``event_code`` column of ``audit_events``.
    """
    audit = AuditEvent(
        id=str(uuid.uuid4()),
        entity_type=entity_type,
        entity_id=entity_id,
        event_code=event_code,
        actor_id=actor.actor_id,
        occurred_at=now,
        payload=None,
    )
    uow._session.add(audit)
    uow._session.flush()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ApplicationService:
    """
    Coordinates Application and Intake creation/update use cases (A01).

    Each public method opens exactly one UoW, performs all reads and writes
    inside it, commits on success, and returns a plain dict.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # create_application  (section 25.1)
    # ------------------------------------------------------------------

    def create_application(self, cmd: CreateApplicationCommand) -> dict:
        """
        Create a new application.

        Steps:
        1. Normalize display_name.
        2. Normalize each identifier; reject intra-command duplicates.
        3. Reject cross-application normalized duplicates.
        4. Upsert actor row.
        5. Insert application row (state=ACTIVE, row_version=1).
        6. Insert identifier rows.
        7. Write APPLICATION_CREATED audit event.
        8. Commit.

        Returns a plain dict with keys: id, display_name, state.
        """
        now = datetime.now(tz=UTC)
        app_id = str(uuid.uuid4())
        display_name = _normalize_name(cmd.display_name)

        with uow_context(self._session_factory) as uow:
            # --- duplicate check: within the command -----------------------
            seen: set[tuple[str, str]] = set()
            for ident in cmd.identifiers:
                normalized = ident.raw_value.strip().lower()
                key = (ident.identifier_type, normalized)
                if key in seen:
                    raise DuplicateIdentifierError(
                        f"Command contains duplicate identifier "
                        f"({ident.identifier_type}, {normalized!r})"
                    )
                seen.add(key)

            # --- duplicate check: against existing applications -----------
            for ident in cmd.identifiers:
                normalized = ident.raw_value.strip().lower()
                existing = uow.applications.get_by_normalized_identifier(
                    ident.identifier_type, normalized
                )
                if existing is not None:
                    raise DuplicateIdentifierError(
                        f"Identifier ({ident.identifier_type}, {normalized!r}) "
                        f"is already assigned to application {existing['id']}"
                    )

            # --- actor, application, identifiers --------------------------
            _ensure_actor(uow, cmd.actor, now)

            uow.applications.add(
                actor_id=cmd.actor.actor_id,
                display_name=display_name,
                state="ACTIVE",
                created_at=now,
                application_id=app_id,
            )

            for ident in cmd.identifiers:
                normalized = ident.raw_value.strip().lower()
                uow.applications.add_identifier(
                    application_id=app_id,
                    identifier_type=ident.identifier_type,
                    raw_value=ident.raw_value,
                    normalized_value=normalized,
                    created_at=now,
                )

            # --- audit ----------------------------------------------------
            _write_audit(
                uow, cmd.actor, "APPLICATION_CREATED", "application", app_id, now
            )
            uow.commit()

        return {"id": app_id, "display_name": display_name, "state": "ACTIVE"}

    # ------------------------------------------------------------------
    # create_intake  (section 25.1)
    # ------------------------------------------------------------------

    def create_intake(self, cmd: CreateIntakeCommand) -> dict:
        """
        Create an intake for an active application with a published catalog.

        Steps:
        1. Load application; raise ApplicationNotFoundError if absent.
        2. Raise ApplicationNotActiveError if not ACTIVE.
        3. Load catalog release; raise CatalogNotPublishedError if not PUBLISHED.
        4. Raise OpenIntakeExistsError if an open intake already exists.
        5. Upsert actor row.
        6. Insert intake row (state=DRAFT, row_version=1).
        7. Write INTAKE_CREATED audit event.
        8. Commit.

        Returns a plain dict with keys: id, application_id, catalog_id, state.
        """
        now = datetime.now(tz=UTC)
        intake_id = str(uuid.uuid4())

        with uow_context(self._session_factory) as uow:
            # --- load + validate application ------------------------------
            app = uow.applications.get(cmd.application_id)
            if app is None:
                raise ApplicationNotFoundError(
                    f"Application {cmd.application_id!r} not found"
                )
            if app["state"] != "ACTIVE":
                raise ApplicationNotActiveError(
                    f"Application {cmd.application_id!r} is in state "
                    f"{app['state']!r}; only ACTIVE applications accept intakes"
                )

            # --- validate catalog -----------------------------------------
            catalog = uow.catalogs.get_release(cmd.catalog_release_id)
            if catalog is None or catalog["pub_state"] != "PUBLISHED":
                raise CatalogNotPublishedError(
                    f"Catalog release {cmd.catalog_release_id!r} is not PUBLISHED"
                )

            # --- open-intake policy --------------------------------------
            open_intake = uow.intakes.get_open_intake_for_application(
                cmd.application_id
            )
            if open_intake is not None:
                raise OpenIntakeExistsError(
                    f"Application {cmd.application_id!r} already has an open "
                    f"intake {open_intake['id']!r} in state {open_intake['state']!r}"
                )

            # --- actor, intake -------------------------------------------
            _ensure_actor(uow, cmd.actor, now)

            uow.intakes.add(
                intake_id=intake_id,
                application_id=cmd.application_id,
                catalog_id=cmd.catalog_release_id,
                state="DRAFT",
                created_by_id=cmd.actor.actor_id,
                created_at=now,
            )

            # --- audit ---------------------------------------------------
            _write_audit(
                uow, cmd.actor, "INTAKE_CREATED", "intake", intake_id, now
            )
            uow.commit()

        return {
            "id": intake_id,
            "application_id": cmd.application_id,
            "catalog_id": cmd.catalog_release_id,
            "state": "DRAFT",
        }

    # ------------------------------------------------------------------
    # update_application_identity  (section 25.1)
    # ------------------------------------------------------------------

    def update_application_identity(
        self, cmd: UpdateApplicationIdentityCommand
    ) -> dict:
        """
        Update an application's display_name and identifiers.

        Steps:
        1. Load application; raise ApplicationNotFoundError if absent.
        2. Enforce expected_version; raise ConcurrencyConflictError on mismatch.
        3. Normalize identifiers; reject intra-command duplicates.
        4. Reject cross-application normalized duplicates (excluding self).
        5. Atomically update display_name + row_version via versioned UPDATE.
        6. Replace all identifier rows (delete-then-insert).
        7. Upsert actor row and write APPLICATION_UPDATED audit event.
        8. Commit.

        Returns a plain dict with keys: id, display_name, state.
        """
        from migration_intake.persistence.models import Application

        now = datetime.now(tz=UTC)
        display_name = _normalize_name(cmd.display_name)

        with uow_context(self._session_factory) as uow:
            # --- load + validate ------------------------------------------
            app = uow.applications.get(cmd.application_id)
            if app is None:
                raise ApplicationNotFoundError(
                    f"Application {cmd.application_id!r} not found"
                )
            if app["row_version"] != cmd.expected_version:
                raise ConcurrencyConflictError(
                    f"Expected row_version={cmd.expected_version}, "
                    f"current row_version={app['row_version']}; "
                    "stale update rejected"
                )

            # --- duplicate check: within the command ----------------------
            seen: set[tuple[str, str]] = set()
            for ident in cmd.identifiers:
                normalized = ident.raw_value.strip().lower()
                key = (ident.identifier_type, normalized)
                if key in seen:
                    raise DuplicateIdentifierError(
                        f"Command contains duplicate identifier "
                        f"({ident.identifier_type}, {normalized!r})"
                    )
                seen.add(key)

            # --- duplicate check: against other applications --------------
            for ident in cmd.identifiers:
                normalized = ident.raw_value.strip().lower()
                existing = uow.applications.get_by_normalized_identifier(
                    ident.identifier_type, normalized
                )
                if existing is not None and existing["id"] != cmd.application_id:
                    raise DuplicateIdentifierError(
                        f"Identifier ({ident.identifier_type}, {normalized!r}) "
                        f"is already assigned to application {existing['id']}"
                    )

            # --- atomic update of display_name + row_version --------------
            stmt = (
                update(Application)
                .where(
                    Application.id == cmd.application_id,
                    Application.row_version == cmd.expected_version,
                )
                .values(
                    display_name=display_name,
                    row_version=Application.row_version + 1,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            result = uow._session.execute(stmt)
            if result.rowcount == 0:
                raise ConcurrencyConflictError(
                    "Concurrent modification detected during update"
                )

            # --- replace identifiers: delete old, insert new --------------
            del_stmt = delete(ApplicationIdentifier).where(
                ApplicationIdentifier.application_id == cmd.application_id
            )
            uow._session.execute(del_stmt)

            for ident in cmd.identifiers:
                normalized = ident.raw_value.strip().lower()
                uow.applications.add_identifier(
                    application_id=cmd.application_id,
                    identifier_type=ident.identifier_type,
                    raw_value=ident.raw_value,
                    normalized_value=normalized,
                    created_at=now,
                )

            uow.intakes.bump_application_content_epochs(cmd.application_id)

            # --- actor + audit --------------------------------------------
            _ensure_actor(uow, cmd.actor, now)
            _write_audit(
                uow,
                cmd.actor,
                "APPLICATION_UPDATED",
                "application",
                cmd.application_id,
                now,
            )
            uow.commit()

        return {
            "id": cmd.application_id,
            "display_name": display_name,
            "state": app["state"],
        }
