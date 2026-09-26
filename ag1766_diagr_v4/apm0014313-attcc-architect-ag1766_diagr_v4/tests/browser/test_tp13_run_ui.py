"""TP13 truthful topology run-detail browser states."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from playwright.sync_api import Page, expect

from migration_intake.persistence.models import Intake
from migration_intake.persistence.models_topology import GenerationRun, TopologyBaseArtifact

pytestmark = pytest.mark.browser


@pytest.fixture()
def run_ui_context(session_factory, intake):
    now = datetime.now(UTC)
    base_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    with session_factory() as session:
        actor_id = str(session.get(Intake, intake["intake_id"]).created_by_id)
        session.add(
            TopologyBaseArtifact(
                id=base_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                filename="approved.drawio",
                mime_type="application/xml",
                size_bytes=1,
                sha256_hex="a" * 64,
                content_address="aa/" + "a" * 64,
                uploaded_by_id=actor_id,
                uploaded_at=now,
                created_at=now,
                review_state="APPROVED",
                authority="DRAFT_PREVIEW",
                lifecycle="ACTIVE",
                row_version=1,
            )
        )
        session.flush()
        session.add(
            GenerationRun(
                id=run_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                base_artifact_id=base_id,
                base_sha256="a" * 64,
                mode="DRAFT_PREVIEW",
                capability="LABEL_ONLY",
                authority="DRAFT_PREVIEW",
                phase="COMPLETED",
                status="GENERATED_WITH_GAPS",
                approval_status="PENDING",
                row_version=1,
                requested_by_id=actor_id,
                requested_at=now,
                completed_at=now,
                created_at=now,
            )
        )
        session.commit()
    return {**intake, "run_id": run_id}


def _url(app_server: str, context: dict) -> str:
    return (
        f"{app_server}/applications/{context['application_id']}"
        f"/intakes/{context['intake_id']}/topology/runs/{context['run_id']}"
    )


@pytest.mark.parametrize(
    "viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}]
)
def test_preview_run_is_truthful_responsive_and_has_no_approval(
    page: Page, app_server: str, run_ui_context: dict, viewport: dict
) -> None:
    page.set_viewport_size(viewport)
    response = page.goto(_url(app_server, run_ui_context))
    assert response is not None and response.ok
    expect(page.get_by_text("DRAFT PREVIEW", exact=True)).to_be_visible()
    expect(page.get_by_text("Generated with gaps requiring review")).to_be_visible()
    expect(page.get_by_text("Draft previews are not eligible for approval.")).to_be_visible()
    expect(page.get_by_role("button", name="Record decision")).to_have_count(0)
    overflow = page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    assert overflow


def test_failed_and_incomplete_bundle_are_truthful(
    page: Page, app_server: str, session_factory, run_ui_context: dict
) -> None:
    with session_factory() as session:
        run = session.get(GenerationRun, run_ui_context["run_id"])
        run.phase = "FAILED"
        run.status = "FAILED"
        run.error_code = "SYNTHETIC_FAILURE"
        run.error_message = "Synthetic safe error"
        session.commit()
    response = page.goto(_url(app_server, run_ui_context))
    assert response is not None and response.ok
    expect(page.get_by_text("Generation failed")).to_be_visible()
    expect(page.get_by_text("Error: Synthetic safe error")).to_be_visible()
    expect(page.get_by_role("link", name="Download diagram")).to_have_count(0)
