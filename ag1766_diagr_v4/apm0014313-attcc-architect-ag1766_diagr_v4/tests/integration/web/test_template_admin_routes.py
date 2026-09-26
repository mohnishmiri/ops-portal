"""Integration tests for topology template admin routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from migration_intake.application.dto import ActorContext
from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.models import Actor, Base
from migration_intake.persistence.repositories.templates import TemplateRepository
from migration_intake.web.security import generate_csrf_token


def _make_app(tmp_path):
    actor_id = "00000000-0000-0000-0000-000000000001"
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'template-admin.db'}",
        app_env="test",
        evidence_root=str(tmp_path / "evidence"),
        actor_id=actor_id,
        actor_display_name="Template Admin",
        csrf_secret="test-csrf-secret-key-12345",
        llm_enabled=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as session:
        session.add(Actor(id=actor_id, display_name="Template Admin", created_at=datetime.now(tz=UTC)))
        session.commit()
    return app, actor_id


def _seed_release(app, *, version: str = "1.8", state: str = "PUBLISHED") -> str:
    with app.state.session_factory() as session:
        row = TemplateRepository(session).add_release(
            release_id=str(uuid.uuid4()),
            template_version=version,
            source_filename=f"outpost_v{version}.drawio",
            source_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            content_address="aa/" + ("a" * 64),
            size_bytes=100,
            tab_count=4,
            variant_manifest=[{"variant": "basic", "tab_name": "Without LBs", "role_count": 45}],
            compiler_version="1.0.0",
            compiler_report={"diagnostics": []},
            pub_state=state,
            published_at=datetime.now(tz=UTC) if state == "PUBLISHED" else None,
            published_by_id="00000000-0000-0000-0000-000000000001",
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
        return row["id"]


def test_list_page_renders_empty_state(tmp_path) -> None:
    app, _actor_id = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/admin/templates")
    assert response.status_code == 200
    assert "No template releases have been published yet" in response.text


def test_list_page_renders_releases_table(tmp_path) -> None:
    app, _actor_id = _make_app(tmp_path)
    _seed_release(app, version="1.8", state="PUBLISHED")
    with TestClient(app) as client:
        response = client.get("/admin/templates")
    assert response.status_code == 200
    assert "Template Releases" in response.text
    assert "1.8" in response.text


def test_detail_page_returns_404_for_unknown(tmp_path) -> None:
    app, _actor_id = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get(f"/admin/templates/{uuid.uuid4()}")
    assert response.status_code == 404


def test_upload_form_renders_with_csrf_token(tmp_path) -> None:
    app, _actor_id = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/admin/templates/upload")
    assert response.status_code == 200
    assert "_csrf_token" in response.text


def test_publish_requires_csrf_token(tmp_path) -> None:
    app, _actor_id = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/admin/templates/publish",
            data={"template_version": "1.8"},
            files={"file": ("template.drawio", b"<mxfile></mxfile>", "application/xml")},
        )
    assert response.status_code == 403


def test_publish_valid_template_creates_release(tmp_path, monkeypatch) -> None:
    app, actor_id = _make_app(tmp_path)

    class FakePublishService:
        def __init__(self, _session_factory, storage_root=None):
            pass

        def publish(self, content, filename, *, template_version, actor):
            assert actor == ActorContext(actor_id=actor_id, role_codes=actor.role_codes)
            return {
                "id": str(uuid.uuid4()),
                "template_version": template_version,
                "pub_state": "PUBLISHED",
            }

    monkeypatch.setattr(
        "migration_intake.web.routes.template_admin_publish.TemplateAdminPublishService",
        FakePublishService,
    )

    with TestClient(app) as client:
        response = client.post(
            "/admin/templates/publish",
            data={
                "_csrf_token": generate_csrf_token(app.state.settings.csrf_secret),
                "template_version": "1.8",
            },
            files={"file": ("template.drawio", b"<mxfile></mxfile>", "application/xml")},
        )
    assert response.status_code == 201


def test_activate_sets_active_release(tmp_path, monkeypatch) -> None:
    app, _actor_id = _make_app(tmp_path)
    release_id = _seed_release(app, version="1.8", state="DRAFT")

    class FakePublishService:
        def __init__(self, _session_factory, storage_root=None):
            pass

        def activate(self, rel_id, *, actor):
            assert rel_id == release_id
            return {"id": rel_id, "pub_state": "PUBLISHED"}

    monkeypatch.setattr(
        "migration_intake.web.routes.template_admin_publish.TemplateAdminPublishService",
        FakePublishService,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/admin/templates/{release_id}/activate",
            data={"_csrf_token": generate_csrf_token(app.state.settings.csrf_secret)},
        )
    assert response.status_code == 200
    assert response.json()["pub_state"] == "PUBLISHED"


def test_retire_sets_retired_state(tmp_path, monkeypatch) -> None:
    app, _actor_id = _make_app(tmp_path)
    release_id = _seed_release(app, version="1.8", state="PUBLISHED")

    class FakePublishService:
        def __init__(self, _session_factory, storage_root=None):
            pass

        def retire(self, rel_id, *, actor):
            assert rel_id == release_id
            return {"id": rel_id, "pub_state": "RETIRED"}

    monkeypatch.setattr(
        "migration_intake.web.routes.template_admin_publish.TemplateAdminPublishService",
        FakePublishService,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/admin/templates/{release_id}/retire",
            data={"_csrf_token": generate_csrf_token(app.state.settings.csrf_secret)},
        )
    assert response.status_code == 200
    assert response.json()["pub_state"] == "RETIRED"
