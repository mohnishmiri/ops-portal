"""TP15 three-run Playwright restart and receipt certification."""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from migration_intake.persistence.models import Intake
from migration_intake.persistence.models_topology import (
    GeneratedArtifact,
    GenerationRun,
    TopologyBaseArtifact,
)
from migration_intake.storage.filesystem import FilesystemStore

pytestmark = pytest.mark.browser


@pytest.fixture()
def completed_preview_bundle(session_factory: Any, intake: dict, evidence_root) -> dict:
    now = datetime.now(UTC)
    base_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    storage = FilesystemStore(evidence_root / "topology")
    contents = {
        "DIAGRAM": (
            b'<mxfile host="app.diagrams.net">'
            b'<diagram name="Certified">'
            b"<mxGraphModel><root>"
            b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
            b'<mxCell id="n1" value="Certified Node" vertex="1" parent="1">'
            b'<mxGeometry x="80" y="80" width="160" height="60" as="geometry"/>'
            b"</mxCell></root></mxGraphModel>"
            b"</diagram></mxfile>"
        ),
        "GAP_REPORT": b"<html>Certified synthetic report</html>",
        "MANIFEST": json.dumps(
            {"result_status": "READY_FOR_REVIEW"}, separators=(",", ":")
        ).encode(),
    }
    with session_factory() as session:
        actor_id = str(session.get(Intake, intake["intake_id"]).created_by_id)
        session.add(
            TopologyBaseArtifact(
                id=base_id,
                application_id=intake["application_id"],
                intake_id=intake["intake_id"],
                filename="certified.drawio",
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
        manifest_hash = hashlib.sha256(contents["MANIFEST"]).hexdigest()
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
                status="READY_FOR_REVIEW",
                readiness_json={"status": "READY_FOR_REVIEW", "blockers": [], "warnings": []},
                approval_status="PENDING",
                row_version=1,
                requested_by_id=actor_id,
                requested_at=now,
                completed_at=now,
                created_at=now,
                manifest_hash=manifest_hash,
            )
        )
        session.flush()
        for artifact_type, content in contents.items():
            receipt = storage.store(io.BytesIO(content), artifact_type.lower())
            session.add(
                GeneratedArtifact(
                    id=str(uuid.uuid4()),
                    generation_run_id=run_id,
                    artifact_type=artifact_type,
                    filename=f"{artifact_type.lower()}.bin",
                    mime_type="application/json"
                    if artifact_type == "MANIFEST"
                    else "application/octet-stream",
                    size_bytes=len(content),
                    sha256_hex=receipt.sha256_hex,
                    content_address=receipt.storage_key,
                    created_at=now,
                )
            )
        session.commit()
    return {**intake, "run_id": run_id, "contents": contents}


@pytest.mark.parametrize("journey", [1, 2, 3])
def test_artifacts_are_identical_after_restart(
    page: Page,
    restartable_app_server: Any,
    completed_preview_bundle: dict,
    journey: int,
    tmp_path: Path,
) -> None:
    context = completed_preview_bundle
    path = (
        f"/applications/{context['application_id']}/intakes/{context['intake_id']}"
        f"/topology/runs/{context['run_id']}"
    )
    response = page.goto(f"{restartable_app_server.base_url}{path}")
    assert response is not None and response.ok
    expect(page.get_by_text("DRAFT PREVIEW", exact=True)).to_be_visible()
    evidence_dir = Path(os.environ.get("TP15_SIGNOFF_DIR", str(tmp_path)))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence_dir / f"journey-{journey}-run.png"), full_page=True)

    def download() -> dict[str, bytes]:
        responses = {
            name: page.request.get(f"{restartable_app_server.base_url}{path}/{name}")
            for name in ("diagram", "report", "manifest")
        }
        assert all(item.status == 200 for item in responses.values()), journey
        return {name: item.body() for name, item in responses.items()}

    before = download()
    before_hashes = {name: hashlib.sha256(value).hexdigest() for name, value in before.items()}
    (evidence_dir / f"journey-{journey}-diagram.drawio").write_bytes(before["diagram"])
    (evidence_dir / f"journey-{journey}-report.html").write_bytes(before["report"])
    (evidence_dir / f"journey-{journey}-manifest.json").write_bytes(before["manifest"])
    (evidence_dir / f"journey-{journey}-receipts.json").write_text(
        json.dumps(before_hashes, sort_keys=True, indent=2), encoding="utf-8"
    )
    restartable_app_server.restart()
    after = download()
    assert after == before
    assert {
        name: hashlib.sha256(value).hexdigest() for name, value in after.items()
    } == before_hashes
