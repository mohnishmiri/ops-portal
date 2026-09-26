"""Route regression tests for topology run authorization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.models import (
    Actor,
    Application,
    Base,
    CatalogRelease,
    Intake,
)
from migration_intake.persistence.models_topology import (
    GenerationRun,
    TopologyBaseArtifact,
)
from migration_intake.web.security import Capability, generate_csrf_token


@pytest.fixture
def topology_context(tmp_path):
    """Create two applications, two intakes, and one scoped generation run."""
    actor_id = str(uuid.uuid4())
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'topology-routes.db'}",
        app_env="test",
        evidence_root=str(tmp_path / "evidence"),
        actor_id=actor_id,
        actor_display_name="Topology Test Actor",
        csrf_secret="test-csrf-secret-key-12345",  # noqa: S106 - synthetic test setting
        llm_enabled=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)

    application_id = str(uuid.uuid4())
    other_application_id = str(uuid.uuid4())
    intake_id = str(uuid.uuid4())
    other_intake_id = str(uuid.uuid4())
    other_application_intake_id = str(uuid.uuid4())
    catalog_id = str(uuid.uuid4())
    base_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)

    with app.state.session_factory() as session:
        session.add(Actor(id=actor_id, display_name="Topology Test Actor", created_at=now))
        session.add_all(
            [
                Application(
                    id=application_id,
                    state="ACTIVE",
                    display_name="Topology Test Application",
                    created_at=now,
                    updated_at=now,
                    row_version=1,
                    created_by_id=actor_id,
                ),
                Application(
                    id=other_application_id,
                    state="ACTIVE",
                    display_name="Other Application",
                    created_at=now,
                    updated_at=now,
                    row_version=1,
                    created_by_id=actor_id,
                ),
                CatalogRelease(
                    id=catalog_id,
                    semantic_version="1.0.0",
                    source_filename="synthetic-catalog.yaml",
                    source_sha256="b" * 64,
                    compiler_version="1.0",
                    pub_state="PUBLISHED",
                    published_at=now,
                    created_at=now,
                ),
            ]
        )
        session.add_all(
            [
                Intake(
                    id=intake_id,
                    application_id=application_id,
                    catalog_id=catalog_id,
                    state="DRAFT",
                    created_at=now,
                    updated_at=now,
                    row_version=1,
                    created_by_id=actor_id,
                ),
                Intake(
                    id=other_intake_id,
                    application_id=application_id,
                    catalog_id=catalog_id,
                    state="DRAFT",
                    created_at=now,
                    updated_at=now,
                    row_version=1,
                    created_by_id=actor_id,
                ),
                Intake(
                    id=other_application_intake_id,
                    application_id=other_application_id,
                    catalog_id=catalog_id,
                    state="DRAFT",
                    created_at=now,
                    updated_at=now,
                    row_version=1,
                    created_by_id=actor_id,
                ),
            ]
        )
        session.flush()
        session.add(
            TopologyBaseArtifact(
                id=base_id,
                application_id=application_id,
                intake_id=intake_id,
                filename="synthetic.drawio",
                mime_type="application/vnd.jgraph.mxfile+xml",
                size_bytes=12,
                sha256_hex="a" * 64,
                content_address="aa/" + "a" * 64,
                uploaded_by_id=actor_id,
                uploaded_at=now,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            GenerationRun(
                id=run_id,
                application_id=application_id,
                intake_id=intake_id,
                snapshot_id=None,
                snapshot_sha256=None,
                catalog_sha256=None,
                base_artifact_id=base_id,
                base_sha256="a" * 64,
                status="READY_FOR_REVIEW",
                approval_status="PENDING",
                requested_by_id=actor_id,
                requested_at=now,
                created_at=now,
            )
        )
        session.commit()

    return {
        "app": app,
        "app_id": application_id,
        "other_app_id": other_application_id,
        "intake_id": intake_id,
        "other_intake_id": other_intake_id,
        "other_app_intake_id": other_application_intake_id,
        "base_id": base_id,
        "run_id": run_id,
    }


@pytest.mark.parametrize("suffix", ["", "/diagram", "/report", "/manifest"])
def test_topology_run_routes_reject_wrong_intake_scope(
    topology_context,
    suffix: str,
) -> None:
    """A valid run cannot be addressed through another intake in its app."""
    context = topology_context
    path = (
        f"/applications/{context['app_id']}/intakes/"
        f"{context['other_intake_id']}/topology/runs/{context['run_id']}{suffix}"
    )

    with TestClient(context["app"]) as client:
        response = client.get(path)

    assert response.status_code == 404


@pytest.mark.parametrize("suffix", ["", "/diagram", "/report", "/manifest"])
def test_topology_run_routes_reject_wrong_application_scope(
    topology_context,
    suffix: str,
) -> None:
    """A valid run cannot be addressed through another application."""
    context = topology_context
    path = (
        f"/applications/{context['other_app_id']}/intakes/"
        f"{context['other_app_intake_id']}/topology/runs/{context['run_id']}{suffix}"
    )

    with TestClient(context["app"]) as client:
        response = client.get(path)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("path_suffix", "method", "capability"),
    [
        ("/topology/generate", "post", Capability.TOPOLOGY_GENERATE),
        (
            "/topology/runs/{run_id}/diagram",
            "get",
            Capability.TOPOLOGY_ARTIFACT_DOWNLOAD,
        ),
        (
            "/topology/runs/{run_id}/report",
            "get",
            Capability.TOPOLOGY_ARTIFACT_DOWNLOAD,
        ),
        (
            "/topology/runs/{run_id}/manifest",
            "get",
            Capability.TOPOLOGY_ARTIFACT_DOWNLOAD,
        ),
    ],
)
def test_topology_routes_reject_missing_capability(
    topology_context,
    path_suffix: str,
    method: str,
    capability: Capability,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Topology actions deny before service methods can be reached."""
    context = topology_context
    path = path_suffix.format(run_id=context["run_id"])
    path = f"/applications/{context['app_id']}/intakes/{context['intake_id']}" + path

    capabilities = set(Capability)
    capabilities.remove(capability)
    monkeypatch.setattr(
        "migration_intake.web.routes.topology.CONFIGURED_ACTOR_CAPABILITIES",
        frozenset(capabilities),
    )

    with TestClient(context["app"]) as client:
        if method == "post":
            response = client.post(path, data={"_csrf_token": "synthetic"})
        else:
            response = client.get(path)

    assert response.status_code == 403


def test_generation_accepts_uploaded_base_without_status_gate(topology_context) -> None:
    """Temporary test generation accepts a scoped uploaded base in DRAFT state."""
    context = topology_context

    class FakeTopologyService:
        def generate_topology(self, **_kwargs):
            return {"id": context["run_id"]}

    from migration_intake.web.routes.topology import get_topology_service

    context["app"].dependency_overrides[get_topology_service] = FakeTopologyService

    with TestClient(context["app"]) as client:
        response = client.post(
            f"/applications/{context['app_id']}/intakes/{context['intake_id']}/topology/generate",
            data={
                "_csrf_token": generate_csrf_token(context["app"].state.settings.csrf_secret),
                "base_artifact_id": context["base_id"],
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith(f"/topology/runs/{context['run_id']}")


def test_landing_allows_generation_from_draft_upload_and_marks_history_unverified(
    topology_context,
) -> None:
    """Every validated upload is selectable for non-authoritative test generation."""
    context = topology_context

    with TestClient(context["app"]) as client:
        response = client.get(
            f"/applications/{context['app_id']}/intakes/{context['intake_id']}/topology"
        )

    assert response.status_code == 200
    assert (
        'action="'
        + f"/applications/{context['app_id']}/intakes/{context['intake_id']}/topology/generate"
        in response.text
    )
    assert 'id="base_artifact_id"' in response.text
    assert "Generate topology" in response.text
    assert "Official generation and approval remain disabled" in response.text
    assert "LEGACY_UNPINNED" in response.text


def test_upload_rejects_missing_capability_before_reading_file(
    topology_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload authorization runs before the upload is read or stored."""
    context = topology_context
    capabilities = set(Capability)
    capabilities.remove(Capability.TOPOLOGY_BASE_UPLOAD)
    monkeypatch.setattr(
        "migration_intake.web.routes.topology.CONFIGURED_ACTOR_CAPABILITIES",
        frozenset(capabilities),
    )

    with TestClient(context["app"]) as client:
        response = client.post(
            f"/applications/{context['app_id']}/intakes/{context['intake_id']}/topology/upload-base",
            data={"_csrf_token": "synthetic"},
            files={"base_diagram": ("synthetic.drawio", b"synthetic")},
        )

    assert response.status_code == 403


def test_upload_rejects_content_over_limit_after_capability_check(
    topology_context,
) -> None:
    """A permitted upload rejects content beyond the 10 MB boundary."""
    context = topology_context

    with TestClient(context["app"]) as client:
        response = client.post(
            f"/applications/{context['app_id']}/intakes/{context['intake_id']}/topology/upload-base",
            data={"_csrf_token": generate_csrf_token(context["app"].state.settings.csrf_secret)},
            files={
                "base_diagram": (
                    "synthetic.drawio",
                    b"x" * (context["app"].state.settings.max_topology_base_bytes + 1),
                )
            },
        )

    assert response.status_code == 413
    with context["app"].state.session_factory() as session:
        artifacts = (
            session.query(TopologyBaseArtifact).filter_by(intake_id=context["intake_id"]).all()
        )
    assert len(artifacts) == 1


class FakePreviewRunner:
    def __init__(self, run_id: str, *, error: str | None = None) -> None:
        self.run_id = run_id
        self.error = error
        self.calls = 0

    def run_preview(self, **_kwargs):
        self.calls += 1
        if self.error:
            from migration_intake.application.services.topology_runner import GovernedRunnerError

            raise GovernedRunnerError(self.error)
        return {"id": self.run_id}


def _approve_base(context: dict) -> None:
    with context["app"].state.session_factory() as session:
        base = session.query(TopologyBaseArtifact).filter_by(intake_id=context["intake_id"]).one()
        base.review_state = "APPROVED"
        base.compatibility_id = str(uuid.uuid4())
        base.capability = "LABEL_ONLY"
        from migration_intake.persistence.models_topology import TopologyCompatibility

        session.add(
            TopologyCompatibility(
                id=base.compatibility_id,
                base_artifact_id=base.id,
                base_sha256=base.sha256_hex,
                profile_id="SYNTHETIC_LABEL_ONLY",
                profile_version="1",
                profile_hash="c" * 64,
                selection_json={},
                selection_hash="d" * 64,
                capability="LABEL_ONLY",
                parser_policy_hash="e" * 64,
                compatibility_key="f" * 64,
                result_json={},
                result_hash="1" * 64,
                checked_by_id=context["app"].state.settings.actor_id,
                checked_at=datetime.now(UTC),
            )
        )
        session.commit()


def test_governed_preview_success_and_duplicate_reuse(
    topology_context,
) -> None:
    context = topology_context
    _approve_base(context)
    fake = FakePreviewRunner(context["run_id"])
    from migration_intake.web.routes.topology import get_governed_preview_runner

    context["app"].dependency_overrides[get_governed_preview_runner] = lambda: fake
    with context["app"].state.session_factory() as session:
        base_id = str(
            session.query(TopologyBaseArtifact.id)
            .filter_by(intake_id=context["intake_id"])
            .scalar()
        )
    path = f"/applications/{context['app_id']}/intakes/{context['intake_id']}/topology/preview"
    data = {
        "_csrf_token": generate_csrf_token(context["app"].state.settings.csrf_secret),
        "base_artifact_id": base_id,
        "capability": "LABEL_ONLY",
        "environment": "PROD",
        "site_id": "SITE_A",
        "page_name": "Overview",
    }
    with TestClient(context["app"]) as client:
        first = client.post(path, data=data, follow_redirects=False)
        second = client.post(path, data=data, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    assert first.headers["location"] == second.headers["location"]
    assert fake.calls == 2


def test_governed_preview_conflict_returns_409(topology_context) -> None:
    context = topology_context
    _approve_base(context)
    fake = FakePreviewRunner(context["run_id"], error="synthetic conflict")
    from migration_intake.web.routes.topology import get_governed_preview_runner

    context["app"].dependency_overrides[get_governed_preview_runner] = lambda: fake
    with context["app"].state.session_factory() as session:
        base_id = str(
            session.query(TopologyBaseArtifact.id)
            .filter_by(intake_id=context["intake_id"])
            .scalar()
        )
    with TestClient(context["app"]) as client:
        response = client.post(
            f"/applications/{context['app_id']}/intakes/{context['intake_id']}/topology/preview",
            data={
                "_csrf_token": generate_csrf_token(context["app"].state.settings.csrf_secret),
                "base_artifact_id": base_id,
            },
        )
    assert response.status_code == 409
    assert "synthetic conflict" in response.text


class FakeReviewService:
    def __init__(self, payload: tuple[bytes, str, str]) -> None:
        self.payload = payload

    def verified_preview_artifact(self, **_kwargs):
        return self.payload


def test_run_detail_shows_truthful_preview_state_and_manifest(topology_context) -> None:
    context = topology_context
    with context["app"].state.session_factory() as session:
        run = session.get(GenerationRun, context["run_id"])
        run.mode = "DRAFT_PREVIEW"
        run.authority = "DRAFT_PREVIEW"
        run.phase = "COMPLETED"
        session.commit()
    with TestClient(context["app"]) as client:
        response = client.get(
            f"/applications/{context['app_id']}/intakes/{context['intake_id']}"
            f"/topology/runs/{context['run_id']}"
        )
    assert response.status_code == 200
    assert "DRAFT PREVIEW" in response.text
    assert "Draft previews are not eligible for approval" in response.text
    assert "Record decision" not in response.text


def test_manifest_download_uses_verified_preview_service(topology_context) -> None:
    context = topology_context
    with context["app"].state.session_factory() as session:
        run = session.get(GenerationRun, context["run_id"])
        run.mode = "DRAFT_PREVIEW"
        run.phase = "COMPLETED"
        session.commit()
    from migration_intake.web.routes.topology import get_topology_review_service

    context["app"].dependency_overrides[get_topology_review_service] = lambda: FakeReviewService(
        (b'{"result_status":"READY_FOR_REVIEW"}', "manifest.json", "application/json")
    )
    with TestClient(context["app"]) as client:
        response = client.get(
            f"/applications/{context['app_id']}/intakes/{context['intake_id']}"
            f"/topology/runs/{context['run_id']}/manifest"
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content.startswith(b"{")


def test_manifest_download_wrong_scope_returns_404_before_delivery(topology_context) -> None:
    context = topology_context
    from migration_intake.web.routes.topology import get_topology_review_service

    context["app"].dependency_overrides[get_topology_review_service] = lambda: FakeReviewService(
        (b"should-not-return", "manifest.json", "application/json")
    )
    with TestClient(context["app"]) as client:
        response = client.get(
            f"/applications/{context['app_id']}/intakes/{context['other_intake_id']}"
            f"/topology/runs/{context['run_id']}/manifest"
        )
    assert response.status_code == 404
