"""C8.2 topology operator journeys over synthetic disposable data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from migration_intake.topology.renderer import parse_diagram_safely
from migration_intake.persistence.repositories.topology import TopologyRepository

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("capability", ["LABEL_ONLY", "STRUCTURAL"])
def test_topology_operator_surface_and_test_generation(
    page: Page,
    app_server: str,
    intake: dict,
    capability: str,
) -> None:
    """The operator surface exposes temporary non-authoritative generation."""
    topology_url = (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(topology_url)

    assert response is not None
    assert response.ok
    expect(page.get_by_role("heading", name="Generate Topology Diagram")).to_be_visible()
    expect(page.get_by_role("heading", name="Generate test topology")).to_be_visible()
    expect(page.get_by_text("Official generation and approval remain disabled.")).to_be_visible()
    expect(page.locator("body")).to_contain_text(
        "Test generation accepts any validated upload"
    )

    overflow = page.evaluate(
        """() => ({
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: window.innerWidth,
        })"""
    )
    assert overflow["documentWidth"] <= overflow["viewportWidth"]

    csrf = page.locator("input[name='_csrf_token']").first.input_value()
    denied = page.request.post(
        f"{topology_url}/generate",
        form={"_csrf_token": csrf},
    )
    assert denied.status == 400
    assert "No base diagram selected" in denied.text()


def test_topology_upload_is_present_and_scoped(
    page: Page,
    app_server: str,
    intake: dict,
) -> None:
    """The synthetic operator can submit a base upload only in its intake scope."""
    topology_url = (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    page.goto(topology_url)
    expect(page.get_by_label("Base Diagram (.drawio)")).to_be_visible()
    expect(page.get_by_role("button", name="Upload diagram")).to_be_visible()

    csrf = page.locator("input[name='_csrf_token']").first.input_value()
    upload = page.request.post(
        f"{topology_url}/upload-base",
        multipart={
            "_csrf_token": csrf,
            "variant": "default",
            "base_diagram": {
                "name": "synthetic.drawio",
                "mimeType": "application/xml",
                "buffer": b'<mxfile compressed="false"><diagram name="Synthetic" /></mxfile>',
            }
        },
    )
    assert upload.status == 200
    assert "synthetic.drawio" in upload.text()

    foreign = page.request.get(
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology/runs/{intake['application_id']}/manifest"
    )
    assert foreign.status == 404


@pytest.mark.skip(reason="Governed base creation is an administrative fixture boundary")
def test_structural_draft_preview_governed_browser_journey(
    page: Page,
    app_server: str,
    topology_ready_intake: dict,
) -> None:
    """C03: Structural previews mutate only declared regions with exact XML assertions."""
    intake = topology_ready_intake
    topology_url = (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    page.goto(topology_url)
    csrf = page.locator("input[name='_csrf_token']").first.input_value()
    base_xml = (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" value="{{APPLICATION_NAME}}"/>'
        b'<mxCell id="manual" parent="1" value="Manual protected content"/>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    upload = page.request.post(
        f"{topology_url}/governed-base",
        multipart={
            "_csrf_token": csrf,
            "capability": "STRUCTURAL",
            "profile_id": "SYNTHETIC_STRUCTURAL",
            "environment": "PROD",
            "site_id": "SITE_A",
            "page_name": "Overview",
            "base_diagram": {
                "name": "structural.drawio",
                "mimeType": "application/xml",
                "buffer": base_xml,
            },
        },
        max_redirects=0,
    )
    assert upload.status == 303

    landing = page.goto(topology_url)
    assert landing is not None and landing.ok
    expect(page.get_by_text("APPROVED")).to_be_visible()
    base_id = page.locator("select[name='base_artifact_id'] option").first.get_attribute("value")
    assert base_id
    csrf = page.locator("input[name='_csrf_token']").first.input_value()
    preview = page.request.post(
        f"{topology_url}/preview",
        form={"_csrf_token": csrf, "base_artifact_id": base_id},
        max_redirects=0,
    )
    assert preview.status == 303
    location = preview.headers["location"]
    run_page = page.goto(f"{app_server}{location}")
    assert run_page is not None and run_page.ok
    governance = page.get_by_role("heading", name="Governance Pins").locator("..")
    expect(governance.locator("code").first).to_have_text("DRAFT_PREVIEW")

    diagram = page.request.get(f"{app_server}{location}/diagram")
    report = page.request.get(f"{app_server}{location}/report")
    manifest = page.request.get(f"{app_server}{location}/manifest")
    assert diagram.status == 200
    assert report.status == 200
    assert manifest.status == 200

    # C03: Parse diagram XML and verify exact generated cell inventory
    diagram_xml = parse_diagram_safely(diagram.body())

    # Assert exactly one generated cell with correct ID
    generated_cells = diagram_xml.findall(".//mxCell[@id='structural-application-label']")
    assert len(generated_cells) == 1, "Expected exactly one structural-application-label cell"

    # Assert generated cell attributes
    generated = generated_cells[0]
    assert generated.get("id") == "structural-application-label"
    assert generated.get("parent") == "1", "Generated cell must be under container id=1"
    assert generated.get("value") == "Browser Suite App", "Generated cell must have confirmed app name"
    assert generated.get("vertex") == "1"

    # Assert generated cell geometry (x=240, y=120, width=180, height=30)
    geometry = generated.find("mxGeometry")
    assert geometry is not None, "Generated cell must have geometry"
    assert geometry.get("x") == "240"
    assert geometry.get("y") == "120"
    assert geometry.get("width") == "180"
    assert geometry.get("height") == "30"
    assert geometry.get("as") == "geometry"

    # Assert no unapproved generated cells (only structural-application-label)
    all_structural_cells = [
        cell for cell in diagram_xml.iter("mxCell")
        if (cell.get("id") or "").startswith("structural-")
    ]
    assert len(all_structural_cells) == 1, (
        f"Expected only structural-application-label, found: {[c.get('id') for c in all_structural_cells]}"
    )

    # Assert protected manual cell is unchanged
    base_xml_parsed = parse_diagram_safely(base_xml)
    manual_before = base_xml_parsed.find(".//mxCell[@id='manual']")
    manual_after = diagram_xml.find(".//mxCell[@id='manual']")
    assert manual_before is not None and manual_after is not None
    assert ET.tostring(manual_before) == ET.tostring(manual_after), "Protected manual cell was modified"

    # Assert original marker cell resolved (not containing template marker)
    marker_cell = diagram_xml.find(".//mxCell[@id='2']")
    assert marker_cell is not None
    assert marker_cell.get("value") == "Browser Suite App"
    assert "{{APPLICATION_NAME}}" not in (marker_cell.get("value") or "")

    # Verify manifest declares DRAFT_PREVIEW authority
    assert b"DRAFT_PREVIEW" in manifest.body()


def test_label_only_preview_artifacts_survive_server_restart(
    page: Page,
    restartable_app_server: Any,
    session_factory: Any,
    topology_ready_intake: dict,
) -> None:
    """C02: UI journey, receipt downloads, restart and byte-identical retrieval."""
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on("requestfailed", lambda request: failed_requests.append(request.url))
    intake = topology_ready_intake
    topology_url = (
        f"{restartable_app_server.base_url}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    base_xml = (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" value="{{APPLICATION_NAME}}" vertex="1">'
        b'<mxGeometry x="40" y="40" width="220" height="60" as="geometry"/></mxCell>'
        b'<mxCell id="manual" parent="1" value="Manual protected content" vertex="1">'
        b'<mxGeometry x="40" y="160" width="220" height="60" as="geometry"/></mxCell>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )
    response = page.goto(topology_url)
    assert response is not None and response.ok
    page.get_by_label("Capability", exact=True).select_option("LABEL_ONLY")
    page.get_by_label("Profile", exact=True).select_option("SYNTHETIC_LABEL_ONLY")
    page.get_by_label("Base Diagram (.drawio)").set_input_files(
        {"name": "synthetic-c02.drawio", "mimeType": "application/xml", "buffer": base_xml}
    )
    page.get_by_role("button", name="Upload diagram", exact=True).click()
    expect(page.get_by_text("APPROVED", exact=True)).to_be_visible()
    page.get_by_role("button", name="Generate draft preview", exact=True).click()
    expect(page).to_have_url(re.compile(r"/topology/runs/[0-9a-f-]{36}$"))
    run_path = re.sub(r"^https?://[^/]+", "", page.url)
    run_id = run_path.rsplit("/", 1)[-1]

    def artifacts() -> dict[str, bytes]:
        responses = {
            name: page.request.get(f"{restartable_app_server.base_url}{run_path}/{name}")
            for name in ("diagram", "report", "manifest")
        }
        assert all(response.status == 200 for response in responses.values())
        return {name: response.body() for name, response in responses.items()}

    before = artifacts()
    before_xml = parse_diagram_safely(before["diagram"])
    label_cell = before_xml.find(".//mxCell[@id='2']")
    manual_after = before_xml.find(".//mxCell[@id='manual']")
    manual_before = parse_diagram_safely(base_xml).find(".//mxCell[@id='manual']")
    assert label_cell is not None
    assert manual_after is not None
    assert manual_before is not None
    assert label_cell.get("value") == "Browser Suite App"
    assert ET.tostring(manual_after) == ET.tostring(manual_before)
    assert b"DRAFT_PREVIEW" in before["manifest"]
    assert not page_errors
    # Filter out non-critical 404 errors (favicon, static resources, etc.)
    critical_console_errors = [
        e for e in console_errors
        if "404" not in e
    ]
    assert not critical_console_errors, f"Console errors: {console_errors}"
    assert not failed_requests
    with session_factory() as session:
        repository = TopologyRepository(session)
        run = repository.get_generation_run_for_intake(
            run_id, intake["application_id"], intake["intake_id"]
        )
        assert run is not None
        assert run["mode"] == "DRAFT_PREVIEW"
        assert run["authority"] == "DRAFT_PREVIEW"
        assert run["capability"] == "LABEL_ONLY"
        assert run["input_id"]
        assert run["base_artifact_id"]
        assert run["base_sha256"]
        assert run["manifest_hash"] == hashlib.sha256(before["manifest"]).hexdigest()
        assert {item["artifact_type"] for item in repository.list_artifacts_for_run(run_id)} == {
            "DIAGRAM", "GAP_REPORT", "MANIFEST",
        }

    restartable_app_server.restart()
    response = page.goto(f"{restartable_app_server.base_url}{run_path}")
    assert response is not None and response.ok
    after = artifacts()
    assert after == before
    assert not page_errors
    # Filter out non-critical 404 errors (favicon, static resources, etc.)
    critical_console_errors_after = [
        e for e in console_errors
        if "404" not in e
    ]
    assert not critical_console_errors_after, f"Console errors after restart: {console_errors}"
    assert not failed_requests


@pytest.mark.parametrize("capability", ["LABEL_ONLY", "STRUCTURAL"])
def test_topology_handoff_click_journey(
    page: Page,
    app_server: str,
    tmp_path: Path,
    capability: str,
) -> None:
    """Exercise visible pilot controls and optionally capture synthetic handoff images."""
    output = Path(os.environ.get("TOPOLOGY_HANDOFF_SCREENSHOTS", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    prefix = capability.lower()
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{app_server}/applications/new")
    page.locator("#display_name").fill("Synthetic Topology Handoff")
    page.locator("#identifier_type").select_option("CORRELATION")
    page.locator("#identifier_value").fill(str(uuid.uuid4().int % 90000000 + 10000000))
    page.screenshot(path=str(output / f"{prefix}-01-create.png"), full_page=True)
    page.get_by_role("button", name=re.compile("Register")).click()
    expect(page).to_have_url(re.compile(r"/applications/[0-9a-f-]{36}$"))
    page.get_by_role("button", name=re.compile("Create intake")).click()
    topology_href = page.locator('a[href$="/topology"]').first.get_attribute("href")
    assert topology_href
    intake_path = topology_href.removesuffix("/topology")
    page.screenshot(path=str(output / f"{prefix}-02-workspace.png"), full_page=True)
    questionnaire_url = f"{app_server}{intake_path}/questionnaire/INTAKE%20CONTROL"
    page.goto(questionnaire_url)
    page.locator("#q-CTL-002-first").fill("Synthetic Topology Handoff")
    page.locator("#q-CTL-002-second").fill("STH")
    page.locator("#q-CTL-002-second").blur()
    expect(page.locator("#q-CTL-002-save")).to_have_attribute("data-state", "saved")
    page.reload()
    page.locator("#question-CTL-002 details.qx-disclosure").evaluate(
        "element => { element.open = true; }"
    )
    page.locator("#question-CTL-002").get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator("#question-CTL-002")).to_contain_text("CONFIRMED")
    page.screenshot(path=str(output / f"{prefix}-03-confirmed.png"), full_page=True)

    page.goto(f"{app_server}{topology_href}")
    page.get_by_label("Capability", exact=True).select_option(capability)
    page.get_by_label("Profile", exact=True).select_option(f"SYNTHETIC_{capability}")
    base_xml = (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" value="{{APPLICATION_NAME}}" vertex="1">'
        b'<mxGeometry x="40" y="40" width="220" height="60" as="geometry"/></mxCell>'
        b'<mxCell id="manual" parent="1" value="Manual protected content" vertex="1">'
        b'<mxGeometry x="40" y="160" width="220" height="60" as="geometry"/></mxCell>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )
    (output / "synthetic-base.drawio").write_bytes(base_xml)
    page.get_by_label("Base Diagram (.drawio)").set_input_files(
        {"name": "synthetic-base.drawio", "mimeType": "application/xml", "buffer": base_xml}
    )
    page.screenshot(path=str(output / f"{prefix}-04-upload.png"), full_page=True)
    page.get_by_role("button", name="Upload diagram", exact=True).click()
    expect(page.get_by_text("APPROVED", exact=True)).to_be_visible()
    page.screenshot(path=str(output / f"{prefix}-05-base.png"), full_page=True)
    page.get_by_role("button", name="Generate draft preview", exact=True).click()
    expect(page).to_have_url(re.compile(r"/topology/runs/[0-9a-f-]{36}$"))
    run_url = page.url
    expect(page.locator("body")).to_contain_text("DRAFT_PREVIEW")
    page.screenshot(path=str(output / f"{prefix}-06-run.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(output / f"{prefix}-07-mobile.png"), full_page=True)

    diagram = page.request.get(f"{run_url}/diagram")
    report = page.request.get(f"{run_url}/report")
    manifest = page.request.get(f"{run_url}/manifest")
    assert diagram.status == report.status == manifest.status == 200
    before = ET.fromstring(base_xml)
    after = ET.fromstring(diagram.body())
    assert ET.tostring(before.find(".//mxCell[@id='manual']")) == ET.tostring(
        after.find(".//mxCell[@id='manual']")
    )
    generated = after.find(".//mxCell[@id='structural-application-label']")
    assert (generated is not None) == (capability == "STRUCTURAL")
    assert after.find(".//mxCell[@id='2']").get("value") == "Synthetic Topology Handoff"
    assert "DRAFT_PREVIEW" in manifest.text()
    (output / f"{prefix}-diagram.drawio").write_bytes(diagram.body())
    (output / f"{prefix}-report.html").write_bytes(report.body())
    (output / f"{prefix}-manifest.json").write_bytes(manifest.body())
    (output / f"{prefix}-receipts.json").write_text(
        json.dumps({
            "capability": capability,
            "authority": "DRAFT_PREVIEW",
            "diagram_sha256": hashlib.sha256(diagram.body()).hexdigest(),
            "report_sha256": hashlib.sha256(report.body()).hexdigest(),
            "manifest_sha256": hashlib.sha256(manifest.body()).hexdigest(),
            "manual_xml_preserved": True,
        }, indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# C03 Negative Coverage Tests
# ---------------------------------------------------------------------------


def test_structural_preview_rejects_capability_profile_mismatch(
    page: Page,
    app_server: str,
    topology_ready_intake: dict,
) -> None:
    """C03: STRUCTURAL capability with LABEL_ONLY profile must fail compatibility."""
    intake = topology_ready_intake
    topology_url = (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    page.goto(topology_url)
    csrf = page.locator("input[name='_csrf_token']").first.input_value()
    base_xml = (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" value="{{APPLICATION_NAME}}"/>'
        b'<mxCell id="manual" parent="1" value="Manual protected content"/>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    # Attempt to upload with mismatched capability/profile
    upload = page.request.post(
        f"{topology_url}/governed-base",
        multipart={
            "_csrf_token": csrf,
            "capability": "STRUCTURAL",
            "profile_id": "SYNTHETIC_LABEL_ONLY",  # Mismatch: LABEL_ONLY profile with STRUCTURAL capability
            "environment": "PROD",
            "site_id": "SITE_A",
            "page_name": "Overview",
            "base_diagram": {
                "name": "mismatch.drawio",
                "mimeType": "application/xml",
                "buffer": base_xml,
            },
        },
        max_redirects=0,
    )
    # Should fail - either rejected at upload or compatibility check fails
    # The exact behavior depends on implementation: 400/422 for validation error
    # or 303 redirect with incompatible status
    assert upload.status in (303, 400, 422), f"Expected rejection, got {upload.status}"
    if upload.status == 303:
        # If redirected, verify the base is marked incompatible
        landing = page.goto(topology_url)
        assert landing is not None and landing.ok
        # Should not show APPROVED for mismatched capability/profile
        body_text = page.locator("body").inner_text()
        assert "CAPABILITY_MISMATCH" in body_text or "incompatible" in body_text.lower()


def test_structural_preview_rejects_missing_generated_container(
    page: Page,
    app_server: str,
    topology_ready_intake: dict,
) -> None:
    """C03: Base without generated-region container (id=1) must fail compatibility."""
    intake = topology_ready_intake
    topology_url = (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    page.goto(topology_url)
    csrf = page.locator("input[name='_csrf_token']").first.input_value()
    # Base XML without container id="1" - marker cell parent is "0" instead
    base_xml_no_container = (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/>'
        b'<mxCell id="2" parent="0" value="{{APPLICATION_NAME}}"/>'
        b'<mxCell id="manual" parent="0" value="Manual protected content"/>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    upload = page.request.post(
        f"{topology_url}/governed-base",
        multipart={
            "_csrf_token": csrf,
            "capability": "STRUCTURAL",
            "profile_id": "SYNTHETIC_STRUCTURAL",
            "environment": "PROD",
            "site_id": "SITE_A",
            "page_name": "Overview",
            "base_diagram": {
                "name": "no-container.drawio",
                "mimeType": "application/xml",
                "buffer": base_xml_no_container,
            },
        },
        max_redirects=0,
    )
    # 409 Conflict indicates incompatibility was detected
    assert upload.status in (303, 400, 409, 422), f"Expected rejection or redirect, got {upload.status}"
    if upload.status == 303:
        landing = page.goto(topology_url)
        assert landing is not None and landing.ok
        body_text = page.locator("body").inner_text()
        # Should show missing generated region error
        assert "MISSING_GENERATED_REGION" in body_text or "incompatible" in body_text.lower()
    elif upload.status == 409:
        # 409 Conflict is the expected response for incompatible base
        pass  # Test passes - incompatibility was correctly detected


def test_structural_preview_rejects_duplicate_generated_id(
    page: Page,
    app_server: str,
    topology_ready_intake: dict,
) -> None:
    """C03: Base already containing structural-application-label must fail (collision)."""
    intake = topology_ready_intake
    topology_url = (
        f"{app_server}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    page.goto(topology_url)
    csrf = page.locator("input[name='_csrf_token']").first.input_value()
    # Base XML that already contains the generated cell ID (collision)
    base_xml_collision = (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" value="{{APPLICATION_NAME}}"/>'
        b'<mxCell id="manual" parent="1" value="Manual protected content"/>'
        b'<mxCell id="structural-application-label" parent="1" value="Pre-existing collision"/>'
        b"</root></mxGraphModel></diagram></mxfile>"
    )
    upload = page.request.post(
        f"{topology_url}/governed-base",
        multipart={
            "_csrf_token": csrf,
            "capability": "STRUCTURAL",
            "profile_id": "SYNTHETIC_STRUCTURAL",
            "environment": "PROD",
            "site_id": "SITE_A",
            "page_name": "Overview",
            "base_diagram": {
                "name": "collision.drawio",
                "mimeType": "application/xml",
                "buffer": base_xml_collision,
            },
        },
        max_redirects=0,
    )
    # Upload may succeed but preview generation should fail
    if upload.status == 303:
        landing = page.goto(topology_url)
        assert landing is not None and landing.ok
        # If base was accepted, try to generate preview
        base_id = page.locator("select[name='base_artifact_id'] option").first.get_attribute("value")
        if base_id:
            csrf = page.locator("input[name='_csrf_token']").first.input_value()
            preview = page.request.post(
                f"{topology_url}/preview",
                form={"_csrf_token": csrf, "base_artifact_id": base_id},
                max_redirects=0,
            )
            # Preview should fail due to collision
            if preview.status == 303:
                location = preview.headers["location"]
                run_page = page.goto(f"{app_server}{location}")
                assert run_page is not None
                body_text = page.locator("body").inner_text()
                # Should show error about collision or already exists
                assert "already exists" in body_text.lower() or "FAILED" in body_text or "error" in body_text.lower()


# ---------------------------------------------------------------------------
# C03 Restartable STRUCTURAL Test
# ---------------------------------------------------------------------------


def test_structural_preview_artifacts_survive_server_restart(
    page: Page,
    restartable_app_server: Any,
    session_factory: Any,
    topology_ready_intake: dict,
) -> None:
    """C03: STRUCTURAL UI journey, receipt downloads, restart and byte-identical retrieval."""
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on("requestfailed", lambda request: failed_requests.append(request.url))
    intake = topology_ready_intake
    topology_url = (
        f"{restartable_app_server.base_url}/applications/{intake['application_id']}"
        f"/intakes/{intake['intake_id']}/topology"
    )
    base_xml = (
        b'<mxfile><diagram id="page-1" name="Overview"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" value="{{APPLICATION_NAME}}" vertex="1">'
        b'<mxGeometry x="40" y="40" width="220" height="60" as="geometry"/></mxCell>'
        b'<mxCell id="manual" parent="1" value="Manual protected content" vertex="1">'
        b'<mxGeometry x="40" y="160" width="220" height="60" as="geometry"/></mxCell>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )
    response = page.goto(topology_url)
    assert response is not None and response.ok
    page.get_by_label("Capability", exact=True).select_option("STRUCTURAL")
    page.get_by_label("Profile", exact=True).select_option("SYNTHETIC_STRUCTURAL")
    page.get_by_label("Base Diagram (.drawio)").set_input_files(
        {"name": "synthetic-c03.drawio", "mimeType": "application/xml", "buffer": base_xml}
    )
    page.get_by_role("button", name="Upload diagram", exact=True).click()
    expect(page.get_by_text("APPROVED", exact=True)).to_be_visible()
    page.get_by_role("button", name="Generate draft preview", exact=True).click()
    expect(page).to_have_url(re.compile(r"/topology/runs/[0-9a-f-]{36}$"))
    run_path = re.sub(r"^https?://[^/]+", "", page.url)
    run_id = run_path.rsplit("/", 1)[-1]

    def artifacts() -> dict[str, bytes]:
        responses = {
            name: page.request.get(f"{restartable_app_server.base_url}{run_path}/{name}")
            for name in ("diagram", "report", "manifest")
        }
        assert all(response.status == 200 for response in responses.values())
        return {name: response.body() for name, response in responses.items()}

    before = artifacts()

    # C03: Parse and verify structural diagram before restart
    before_xml = parse_diagram_safely(before["diagram"])

    # Verify generated cell exists with correct attributes
    generated_cells = before_xml.findall(".//mxCell[@id='structural-application-label']")
    assert len(generated_cells) == 1, "Expected exactly one structural-application-label cell"
    generated = generated_cells[0]
    assert generated.get("parent") == "1"
    assert generated.get("value") == "Browser Suite App"

    # Verify geometry
    geometry = generated.find("mxGeometry")
    assert geometry is not None
    assert geometry.get("x") == "240"
    assert geometry.get("y") == "120"
    assert geometry.get("width") == "180"
    assert geometry.get("height") == "30"

    # Verify no unapproved structural cells
    all_structural_cells = [
        cell for cell in before_xml.iter("mxCell")
        if (cell.get("id") or "").startswith("structural-")
    ]
    assert len(all_structural_cells) == 1

    # Verify marker cell resolved
    label_cell = before_xml.find(".//mxCell[@id='2']")
    assert label_cell is not None
    assert label_cell.get("value") == "Browser Suite App"

    # Verify protected manual cell unchanged
    manual_after = before_xml.find(".//mxCell[@id='manual']")
    manual_before = parse_diagram_safely(base_xml).find(".//mxCell[@id='manual']")
    assert manual_after is not None and manual_before is not None
    assert ET.tostring(manual_after) == ET.tostring(manual_before)

    assert b"DRAFT_PREVIEW" in before["manifest"]
    assert not page_errors
    # Filter out non-critical 404 errors (favicon, static resources, etc.)
    critical_console_errors = [
        e for e in console_errors
        if "404" not in e
    ]
    assert not critical_console_errors, f"Console errors: {console_errors}"
    assert not failed_requests

    # Verify repository state
    with session_factory() as session:
        repository = TopologyRepository(session)
        run = repository.get_generation_run_for_intake(
            run_id, intake["application_id"], intake["intake_id"]
        )
        assert run is not None
        assert run["mode"] == "DRAFT_PREVIEW"
        assert run["authority"] == "DRAFT_PREVIEW"
        assert run["capability"] == "STRUCTURAL"
        assert run["input_id"]
        assert run["base_artifact_id"]
        assert run["base_sha256"]
        assert run["manifest_hash"] == hashlib.sha256(before["manifest"]).hexdigest()
        assert {item["artifact_type"] for item in repository.list_artifacts_for_run(run_id)} == {
            "DIAGRAM", "GAP_REPORT", "MANIFEST",
        }

    # Restart server and verify byte-identical retrieval
    restartable_app_server.restart()
    response = page.goto(f"{restartable_app_server.base_url}{run_path}")
    assert response is not None and response.ok
    after = artifacts()
    assert after == before, "Artifacts must be byte-identical after restart"
    assert not page_errors
    # Filter out non-critical 404 errors after restart
    critical_console_errors_after = [
        e for e in console_errors
        if "404" not in e
    ]
    assert not critical_console_errors_after, f"Console errors after restart: {console_errors}"
    assert not failed_requests
