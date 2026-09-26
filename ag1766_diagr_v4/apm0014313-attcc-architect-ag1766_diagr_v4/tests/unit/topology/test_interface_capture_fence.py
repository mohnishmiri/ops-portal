"""TP05 deterministic interface reads and application epoch fencing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.models import Actor, Application
from migration_intake.persistence.repositories.interfaces import InterfaceRepository


def _seed(factory: sessionmaker) -> tuple[str, str]:
    now = datetime.now(UTC)
    actor_id = str(uuid.uuid4())
    application_id = str(uuid.uuid4())
    with factory() as session:
        session.add(Actor(id=actor_id, display_name="Synthetic", created_at=now))
        session.add(
            Application(
                id=application_id,
                state="ACTIVE",
                display_name="Synthetic",
                created_at=now,
                updated_at=now,
                row_version=1,
                interface_epoch=1,
                created_by_id=actor_id,
            )
        )
        session.commit()
    return actor_id, application_id


def _fields(correlation_id: str) -> dict[str, str]:
    return {
        "migrating_app_correlation_id": "APP",
        "interface_correlation_id": correlation_id,
        "interface_app_acronym": correlation_id,
        "interface_system_location": "AWS",
        "data_traffic_direction": "Inbound",
        "target_protocol": "HTTPS",
        "future_port": "443",
        "interface_contact": "excluded@example.test",
        "notes": "excluded free text",
    }


def test_mutations_increment_epoch_once_and_rollback_restores_epoch(tmp_engine) -> None:
    factory = sessionmaker(bind=tmp_engine)
    actor_id, application_id = _seed(factory)
    now = datetime.now(UTC)
    with factory() as session:
        repo = InterfaceRepository(session)
        created = repo.create_record(
            record_id=str(uuid.uuid4()),
            application_id=application_id,
            fields=_fields("IF-1"),
            origin="MANUAL",
            created_at=now,
            created_by_id=actor_id,
        )
        session.commit()
        assert session.get(Application, application_id).interface_epoch == 2
    with factory() as session:
        repo = InterfaceRepository(session)
        repo.update_record(
            record_id=created["id"],
            fields=_fields("IF-1"),
            origin="MANUAL",
            updated_at=now,
            updated_by_id=actor_id,
        )
        session.rollback()
        assert session.get(Application, application_id).interface_epoch == 2
    with factory() as session:
        repo = InterfaceRepository(session)
        repo.retire_record(record_id=created["id"], retired_at=now, retired_by_id=actor_id)
        session.commit()
        assert session.get(Application, application_id).interface_epoch == 3


def test_projection_capture_is_ordered_allowlisted_and_epoch_pinned(tmp_engine) -> None:
    factory = sessionmaker(bind=tmp_engine)
    actor_id, application_id = _seed(factory)
    now = datetime.now(UTC)
    record_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    with factory() as session:
        repo = InterfaceRepository(session)
        pairs = list(zip(record_ids, ("IF-1", "IF-2"), strict=True))
        for record_id, correlation_id in reversed(pairs):
            repo.create_record(
                record_id=record_id,
                application_id=application_id,
                fields=_fields(correlation_id),
                origin="IMPORT",
                created_at=now,
                created_by_id=actor_id,
            )
        session.commit()
    with factory() as session:
        epoch, rows = InterfaceRepository(session).capture_projection_rows(application_id)
    assert epoch == 3
    assert [row["id"] for row in rows] == sorted(record_ids)
    assert all("interface_contact" not in row and "notes" not in row for row in rows)
    assert all("row_version" in row and "created_by_id" in row for row in rows)
