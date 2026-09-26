"""Tests for TemplateAdminPublishService."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from migration_intake.application.dto import ActorContext
from migration_intake.persistence.models import Actor
from migration_intake.persistence.repositories.templates import TemplateRepository


def _seed_actor(session_factory, actor_id: str) -> None:
    with session_factory() as session:
        session.add(
            Actor(id=actor_id, display_name="Template Admin", created_at=datetime.now(tz=UTC))
        )
        session.commit()


def _valid_multitab_template() -> bytes:
    template_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "migration_intake"
        / "topology"
        / "config"
        / "templates"
        / "outpost_v1.7.drawio"
    )
    return template_path.read_bytes()


def test_preview_valid_template_returns_success(session_factory, tmp_path) -> None:
    from migration_intake.application.services.template_admin_publish import (
        TemplateAdminPublishService,
    )

    service = TemplateAdminPublishService(session_factory, storage_root=tmp_path / "evidence")
    result = service.preview(_valid_multitab_template(), "outpost_v1.8.drawio")

    assert result.is_valid is True
    assert result.tab_count >= 4


def test_preview_does_not_persist_to_database(session_factory, tmp_path) -> None:
    from migration_intake.application.services.template_admin_publish import (
        TemplateAdminPublishService,
    )

    service = TemplateAdminPublishService(session_factory, storage_root=tmp_path / "evidence")
    service.preview(_valid_multitab_template(), "outpost_v1.8.drawio")

    with session_factory() as session:
        repo = TemplateRepository(session)
        assert repo.list_releases() == []


def test_publish_valid_template_creates_release(session_factory, tmp_path) -> None:
    from migration_intake.application.services.template_admin_publish import (
        TemplateAdminPublishService,
    )

    actor_id = "00000000-0000-0000-0000-000000000001"
    _seed_actor(session_factory, actor_id)
    service = TemplateAdminPublishService(session_factory, storage_root=tmp_path / "evidence")
    release = service.publish(
        _valid_multitab_template(),
        "outpost_v1.8.drawio",
        template_version="1.8",
        actor=ActorContext(actor_id=actor_id),
    )

    assert release["template_version"] == "1.8"
    assert release["pub_state"] == "PUBLISHED"
    assert release["published_by_id"] == actor_id


def test_publish_duplicate_version_different_content_raises(session_factory, tmp_path) -> None:
    from migration_intake.application.services.template_admin_publish import (
        TemplateAdminPublishService,
        TemplateVersionConflictError,
    )

    actor_id = "00000000-0000-0000-0000-000000000001"
    _seed_actor(session_factory, actor_id)
    service = TemplateAdminPublishService(session_factory, storage_root=tmp_path / "evidence")
    service.publish(
        _valid_multitab_template(),
        "outpost_v1.8.drawio",
        template_version="1.8",
        actor=ActorContext(actor_id=actor_id),
    )

    altered = _valid_multitab_template() + b" "
    with pytest.raises(TemplateVersionConflictError):
        service.publish(
            altered,
            "outpost_v1.8.drawio",
            template_version="1.8",
            actor=ActorContext(actor_id=actor_id),
        )


def test_publish_invalid_template_raises_compile_error(session_factory, tmp_path) -> None:
    from migration_intake.application.services.template_admin_publish import (
        TemplateAdminPublishService,
        TemplateCompileError,
    )

    actor_id = "00000000-0000-0000-0000-000000000001"
    _seed_actor(session_factory, actor_id)
    service = TemplateAdminPublishService(session_factory, storage_root=tmp_path / "evidence")

    with pytest.raises(TemplateCompileError):
        service.publish(
            b"<not-xml>",
            "invalid.drawio",
            template_version="1.8",
            actor=ActorContext(actor_id=actor_id),
        )


def test_retire_sets_retired_state_and_timestamp(session_factory, tmp_path) -> None:
    from migration_intake.application.services.template_admin_publish import (
        TemplateAdminPublishService,
    )

    actor_id = "00000000-0000-0000-0000-000000000001"
    _seed_actor(session_factory, actor_id)
    service = TemplateAdminPublishService(session_factory, storage_root=tmp_path / "evidence")
    release = service.publish(
        _valid_multitab_template(),
        "outpost_v1.8.drawio",
        template_version="1.8",
        actor=ActorContext(actor_id=actor_id),
    )
    retired = service.retire(release["id"], actor=ActorContext(actor_id=actor_id))

    assert retired["pub_state"] == "RETIRED"
    assert retired["retired_at"] is not None
