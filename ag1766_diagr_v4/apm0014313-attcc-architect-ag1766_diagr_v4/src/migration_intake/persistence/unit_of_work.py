"""
SQLAlchemy Unit of Work — one session per command.

Architecture section 32 rules implemented here:
- One UoW owns one SQLAlchemy session and transaction per command.
- Repository methods do NOT commit independently.
- ``flush`` may obtain IDs but is not a transaction boundary.
- Exiting the context manager without an explicit ``commit()`` rolls back.
- Sessions are never shared across requests or background tasks.

Usage::

    with uow_context(session_factory) as uow:
        app = uow.applications.get(app_id)
        uow.applications.update_state(app_id, "ON_HOLD", expected_version=1, ...)
        uow.commit()
    # Exiting without commit → rollback (transaction rolled back on session.close())

Repository access:
    uow.applications  → ApplicationRepository
    uow.catalogs      → CatalogRepository
    uow.intakes       → IntakeRepository
    uow.answers       → AnswerRepository
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker

from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.applications import (
    ApplicationRepository,
)
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository


class UnitOfWork:
    """
    Context manager owning one SQLAlchemy session and transaction.

    Repositories share the single session; the caller commits explicitly
    or the transaction is rolled back on context exit (clean or exceptional).
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self.applications: ApplicationRepository = ApplicationRepository(session)
        self.catalogs: CatalogRepository = CatalogRepository(session)
        self.intakes: IntakeRepository = IntakeRepository(session)
        self.answers: AnswerRepository = AnswerRepository(session)

    # ------------------------------------------------------------------
    # Transaction control
    # ------------------------------------------------------------------

    def commit(self) -> None:
        """Commit the current transaction."""
        self._session.commit()

    def rollback(self) -> None:
        """Explicitly roll back the current transaction."""
        self._session.rollback()

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit the UoW context.

        - On exception: rolls back, then closes the session.
        - On clean exit (no exception): closes the session without an
          explicit rollback.  SQLAlchemy's ``Session.close()`` ends any
          open transaction (rolling it back), so changes made without an
          explicit ``commit()`` are automatically discarded.
        """
        if exc_type is not None:
            self._session.rollback()
        self._session.close()


@contextmanager
def uow_context(
    session_factory: sessionmaker,
) -> Generator[UnitOfWork, None, None]:
    """
    Factory context manager that creates a UnitOfWork from a session factory.

    Preferred entry point when the caller holds a ``sessionmaker`` rather
    than a pre-built ``Session``::

        with uow_context(session_factory) as uow:
            uow.applications.add(...)
            uow.commit()

    On exception the transaction is rolled back before re-raising.
    The session is always closed in the ``finally`` block.
    """
    session: Session = session_factory()
    uow = UnitOfWork(session)
    try:
        yield uow
    except Exception:
        uow.rollback()
        raise
    finally:
        session.close()
