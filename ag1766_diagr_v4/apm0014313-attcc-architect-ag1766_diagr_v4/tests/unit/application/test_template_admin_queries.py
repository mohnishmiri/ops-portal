"""Tests for TemplateAdminQueryService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from migration_intake.persistence.models import Actor
from migration_intake.persistence.repositories.templates import TemplateRepository


def _seed_actor(session_factory, actor_id: str) -> None:
    with session_factory() as session:
        session.add(Actor(id=actor_id, display_name="Template Admin", created_at=datetime.now(tz=UTC)))
        session.commit()


def _seed_release(
    session_factory,
    *,
    template_version: str,
    source_sha256: str,
    pub_state: str,
    published_at: datetime | None,
    created_at: datetime,
    actor_id: str | None,
) -> dict:
    with session_factory() as session:
        repo = TemplateRepository(session)
        row = repo.add_release(
            release_id=str(uuid.uuid4()),
            template_version=template_version,
            source_filename=f"outpost_v{template_version}.drawio",
            source_sha256=source_sha256,
            content_address=f"tpl/{source_sha256}",
            size_bytes=1024,
            tab_count=4,
            variant_manifest=[{"variant": "basic", "tab_name": "Without LBs", "role_count": 40}],
            compiler_version="1.0.0",
            compiler_report={"diagnostics": []},
            pub_state=pub_state,
            published_at=published_at,
            published_by_id=actor_id,
            created_at=created_at,
        )
        session.commit()
        return row


def test_list_releases_returns_all_newest_first(session_factory) -> None:
    from migration_intake.application.services.template_admin_queries import (
        TemplateAdminQueryService,
    )

    actor_id = "00000000-0000-0000-0000-000000000001"
    _seed_actor(session_factory, actor_id)
    first = _seed_release(
        session_factory,
        template_version="1.7",
        source_sha256="1" * 64,
        pub_state="PUBLISHED",
        published_at=datetime.now(tz=UTC) - timedelta(days=1),
        created_at=datetime.now(tz=UTC) - timedelta(days=2),
        actor_id=actor_id,
    )
    second = _seed_release(
        session_factory,
        template_version="1.8",
        source_sha256="2" * 64,
        pub_state="PUBLISHED",
        published_at=datetime.now(tz=UTC),
        created_at=datetime.now(tz=UTC),
        actor_id=actor_id,
    )

    rows = TemplateAdminQueryService(session_factory).list_releases()
    assert [rows[0]["id"], rows[1]["id"]] == [second["id"], first["id"]]


def test_list_releases_marks_is_active(session_factory) -> None:
    from migration_intake.application.services.template_admin_queries import (
        TemplateAdminQueryService,
    )

    actor_id = "00000000-0000-0000-0000-000000000001"
    _seed_actor(session_factory, actor_id)
    _seed_release(
        session_factory,
        template_version="1.7",
        source_sha256="3" * 64,
        pub_state="PUBLISHED",
        published_at=datetime.now(tz=UTC) - timedelta(days=2),
        created_at=datetime.now(tz=UTC) - timedelta(days=2),
        actor_id=actor_id,
    )
    active = _seed_release(
        session_factory,
        template_version="1.8",
        source_sha256="4" * 64,
        pub_state="PUBLISHED",
        published_at=datetime.now(tz=UTC),
        created_at=datetime.now(tz=UTC),
        actor_id=actor_id,
    )

    rows = TemplateAdminQueryService(session_factory).list_releases()
    marked = [row for row in rows if row["is_active"]]
    assert len(marked) == 1
    assert marked[0]["id"] == active["id"]


def test_get_release_detail_returns_none_for_unknown_id(session_factory) -> None:
    from migration_intake.application.services.template_admin_queries import (
        TemplateAdminQueryService,
    )

    detail = TemplateAdminQueryService(session_factory).get_release_detail(str(uuid.uuid4()))
    assert detail is None


def test_get_release_detail_invalid_uuid_returns_none(session_factory) -> None:
    from migration_intake.application.services.template_admin_queries import (
        TemplateAdminQueryService,
    )

    detail = TemplateAdminQueryService(session_factory).get_release_detail("not-a-uuid")
    assert detail is None
