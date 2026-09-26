"""Playwright E2E test: Card 3 'Generate from Standard Template' flow.

Navigates the real UI, selects a variant, submits the form, verifies
the generation run completes, downloads the diagram, and captures
screenshots at every stage as proof.

Usage:
    python scripts/playwright_card3_e2e.py
"""

from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

APP_ID = "96353d13-12fd-4984-bec1-719d1fd8e6da"
INTAKE_ID = "26385e58-8954-4312-bf27-9d8414c79421"
BASE_URL = "http://localhost:8000"
TOPO_URL = f"{BASE_URL}/applications/{APP_ID}/intakes/{INTAKE_ID}/topology"

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "card3-e2e" / RUN_ID
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from playwright.sync_api import sync_playwright

    results: dict = {
        "run_id": RUN_ID,
        "status": "STARTED",
        "steps": [],
        "artifacts": [],
    }

    def step(name: str, status: str = "OK", detail: str = ""):
        entry = {"step": name, "status": status, "detail": detail}
        results["steps"].append(entry)
        icon = "PASS" if status == "OK" else "FAIL" if status == "FAIL" else "INFO"
        print(f"  [{icon}] {name}" + (f" — {detail}" if detail else ""))

    print(f"\n=== Card 3 E2E Test — Run {RUN_ID} ===\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # ── Step 1: Navigate to topology page ──────────────────────────
        print("Step 1: Navigate to topology page")
        page.goto(TOPO_URL, wait_until="networkidle")
        ss1 = ARTIFACT_DIR / "01_topology_page.png"
        page.screenshot(path=str(ss1), full_page=True)
        results["artifacts"].append(str(ss1))

        # Verify all 3 cards are visible
        cards = page.locator(".card").all()
        step(f"Topology page loaded — {len(cards)} cards visible",
             "OK" if len(cards) >= 3 else "FAIL",
             f"Expected >= 3, got {len(cards)}")

        # ── Step 2: Verify Card 3 is present ───────────────────────────
        print("\nStep 2: Verify Card 3 content")
        card3_title = page.locator("text=Generate from Standard Template")
        step("Card 3 title visible",
             "OK" if card3_title.count() > 0 else "FAIL")

        variant_select = page.locator("#standard_variant")
        step("Variant dropdown present",
             "OK" if variant_select.count() > 0 else "FAIL")

        # Check dropdown options
        options = variant_select.locator("option").all()
        option_values = [opt.get_attribute("value") for opt in options]
        step(f"Variant options: {option_values}",
             "OK" if set(option_values) == {"basic", "tlgw", "f5", "hadr"} else "FAIL")

        ss2 = ARTIFACT_DIR / "02_card3_visible.png"
        page.screenshot(path=str(ss2), full_page=True)
        results["artifacts"].append(str(ss2))

        # ── Step 3: Select 'Without LBs' and submit ───────────────────
        print("\nStep 3: Submit Card 3 with variant 'basic'")
        variant_select.select_option("basic")
        ss3 = ARTIFACT_DIR / "03_variant_selected.png"
        page.screenshot(path=str(ss3), full_page=True)
        results["artifacts"].append(str(ss3))

        # Click the generate button within Card 3's form
        card3_form = page.locator("form[action*='generate-standard']")
        generate_btn = card3_form.locator("button[type='submit']")
        step("Generate button found",
             "OK" if generate_btn.count() > 0 else "FAIL")

        # Submit and wait for navigation (redirect to run detail)
        with page.expect_navigation(wait_until="networkidle", timeout=60000):
            generate_btn.click()

        # ── Step 4: Verify we landed on the run detail page ───────────
        print("\nStep 4: Check run detail page")
        current_url = page.url
        is_run_page = "/topology/runs/" in current_url
        step(f"Redirected to run page: {current_url}",
             "OK" if is_run_page else "FAIL")

        ss4 = ARTIFACT_DIR / "04_run_detail_page.png"
        page.screenshot(path=str(ss4), full_page=True)
        results["artifacts"].append(str(ss4))

        # Check for error messages on page
        page_text = page.inner_text("body")
        has_error = "Internal Server Error" in page_text or "500" in page_text
        has_failed = "FAILED" in page_text
        has_completed = "COMPLETED" in page_text or "completed" in page_text.lower()

        if has_error:
            step("Page shows Internal Server Error", "FAIL", page_text[:200])
        elif has_failed:
            step("Run status is FAILED", "FAIL", page_text[:300])
        else:
            step("No error on run detail page", "OK")

        # ── Step 5: Download the generated diagram ─────────────────────
        print("\nStep 5: Download generated diagram")
        diagram_link = page.locator("a[href*='/diagram']")
        if diagram_link.count() > 0:
            diagram_href = diagram_link.first.get_attribute("href")
            step(f"Diagram download link found: {diagram_href}", "OK")

            # Download via the API directly
            full_url = f"{BASE_URL}{diagram_href}"
            response = page.request.get(full_url)
            if response.ok:
                diagram_bytes = response.body()
                diagram_path = ARTIFACT_DIR / "generated_diagram.drawio"
                diagram_path.write_bytes(diagram_bytes)
                results["artifacts"].append(str(diagram_path))
                step(f"Diagram downloaded: {len(diagram_bytes)} bytes", "OK")

                # ── Step 6: Validate the diagram ──────────────────────
                print("\nStep 6: Validate generated diagram")
                try:
                    root = ET.fromstring(diagram_bytes)
                    diagram_el = root.find("diagram")
                    tab_name = diagram_el.get("name", "") if diagram_el is not None else ""
                    step(f"Valid XML, tab name: '{tab_name}'",
                         "OK" if tab_name == "Without LBs" else "FAIL",
                         f"Expected 'Without LBs', got '{tab_name}'")

                    all_cells = list(root.iter("mxCell"))
                    haf_cells = [c for c in all_cells if c.get("haf-role")]
                    step(f"Total cells: {len(all_cells)}, haf-role cells: {len(haf_cells)}", "OK")

                    # Check for generated ATT Internal cells
                    att_gen = [c for c in all_cells if (c.get("id") or "").startswith("att_internal_gen_")]
                    step(f"ATT Internal generated cells: {len(att_gen)}",
                         "OK" if len(att_gen) > 0 else "FAIL")

                    # Check for generated AWS Tier 1 cells
                    aws_gen = [c for c in all_cells if (c.get("id") or "").startswith("aws_tier1_gen_")]
                    step(f"AWS Tier 1 generated cells: {len(aws_gen)}", "OK")

                    # Check standard sections are preserved
                    import re
                    def strip_html(t):
                        return re.sub(r"<[^>]+>", "", t).strip()

                    sections = {
                        "GitHub Runners": False,
                        "JFrog": False,
                        "DNS PHZ": False,
                        "AWS Home Region": False,
                        "DirectConnect": False,
                        "Conexus": False,
                        "Tier 2": False,
                        "Internet": False,
                        "VPCE": False,
                        "SMTP": False,
                        "CloudWatch": False,
                    }
                    for c in all_cells:
                        val = strip_html(c.get("value", "")).lower()
                        for sect in sections:
                            if sect.lower() in val:
                                sections[sect] = True

                    for sect, found in sections.items():
                        step(f"Section '{sect}'", "OK" if found else "FAIL",
                             "present" if found else "MISSING")

                    # Check NO unresolved placeholders from the old dev template
                    needs_cidr = [c for c in all_cells if "NEEDS-CIDR" in strip_html(c.get("value", ""))]
                    step(f"NEEDS-CIDR remaining: {len(needs_cidr)}",
                         "OK" if len(needs_cidr) == 0 else "INFO",
                         "none" if len(needs_cidr) == 0 else f"{len(needs_cidr)} cells")

                except ET.ParseError as e:
                    step(f"XML parse error: {e}", "FAIL")

            else:
                step(f"Diagram download failed: HTTP {response.status}", "FAIL")
        else:
            step("No diagram download link found", "FAIL",
                 "Run may have FAILED — check page content")

        # ── Step 7: Download gap report ────────────────────────────────
        print("\nStep 7: Download gap report")
        report_link = page.locator("a[href*='/report']")
        if report_link.count() > 0:
            report_href = report_link.first.get_attribute("href")
            response = page.request.get(f"{BASE_URL}{report_href}")
            if response.ok:
                report_path = ARTIFACT_DIR / "gap_report.html"
                report_path.write_bytes(response.body())
                results["artifacts"].append(str(report_path))
                step(f"Gap report downloaded: {len(response.body())} bytes", "OK")
            else:
                step(f"Gap report download failed: HTTP {response.status}", "FAIL")
        else:
            step("No gap report link found", "INFO")

        # ── Step 8: Navigate back and verify run appears in list ──────
        print("\nStep 8: Verify run in topology page list")
        page.goto(TOPO_URL, wait_until="networkidle")
        ss8 = ARTIFACT_DIR / "08_topology_page_after.png"
        page.screenshot(path=str(ss8), full_page=True)
        results["artifacts"].append(str(ss8))

        run_rows = page.locator("text=READY_FOR_REVIEW").all()
        if not run_rows:
            run_rows = page.locator("text=COMPLETED").all()
        step(f"Successful runs visible: {len(run_rows)}",
             "OK" if len(run_rows) > 0 else "FAIL")

        # ── Final screenshot ──────────────────────────────────────────
        ss_final = ARTIFACT_DIR / "09_final_state.png"
        page.screenshot(path=str(ss_final), full_page=True)
        results["artifacts"].append(str(ss_final))

        browser.close()

    # ── Summary ───────────────────────────────────────────────────────
    passed = sum(1 for s in results["steps"] if s["status"] == "OK")
    failed = sum(1 for s in results["steps"] if s["status"] == "FAIL")
    results["status"] = "PASSED" if failed == 0 else "FAILED"
    results["passed"] = passed
    results["failed"] = failed

    report_path = ARTIFACT_DIR / "e2e_results.json"
    report_path.write_text(json.dumps(results, indent=2))

    print(f"\n{'='*60}")
    print(f"  Result: {results['status']}  ({passed} passed, {failed} failed)")
    print(f"  Artifacts: {ARTIFACT_DIR}")
    print(f"{'='*60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
