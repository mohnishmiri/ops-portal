"""E2E visual comparison — generate HTML viewer and capture screenshots.

Creates an HTML page that renders draw.io XML via the draw.io embed viewer,
then uses Playwright to capture screenshots for side-by-side comparison.

Usage: python scripts/e2e_visual_comparison.py
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _cell_summary(root: ET.Element) -> dict:
    """Extract a summary of labeled cells by category."""
    cells = {}
    for cell in root.iter("mxCell"):
        cid = cell.get("id", "")
        val = _strip_html(cell.get("value", ""))
        role = cell.get("haf-role", "")
        if val or role:
            cells[cid] = {"value": val[:100], "role": role}
    return cells


def _compare_labels(gen_root: ET.Element, ref_root: ET.Element) -> dict:
    """Compare labeled cells between generated and reference diagrams."""
    gen_labels = set()
    for cell in gen_root.iter("mxCell"):
        val = _strip_html(cell.get("value", ""))
        if val and len(val) > 2:
            gen_labels.add(val[:80])

    ref_labels = set()
    for cell in ref_root.iter("mxCell"):
        val = _strip_html(cell.get("value", ""))
        if val and len(val) > 2:
            ref_labels.add(val[:80])

    return {
        "in_both": sorted(gen_labels & ref_labels),
        "only_in_generated": sorted(gen_labels - ref_labels),
        "only_in_reference": sorted(ref_labels - gen_labels),
    }


def _create_viewer_html(
    gen_xml: str, ref_xml: str, artifact_dir: Path
) -> Path:
    """Create an HTML page with both diagrams rendered side by side."""
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>E2E Diagram Comparison</title>
<style>
  body {{ margin: 0; padding: 20px; font-family: sans-serif; background: #f5f5f5; }}
  h1 {{ text-align: center; }}
  .comparison {{ display: flex; gap: 20px; margin-top: 20px; }}
  .panel {{ flex: 1; background: white; border: 1px solid #ccc; padding: 10px; }}
  .panel h2 {{ margin-top: 0; font-size: 14px; color: #333; }}
  .xml-content {{ width: 100%; height: 600px; overflow: auto;
                  background: #fafafa; border: 1px solid #ddd;
                  padding: 10px; font-family: monospace; font-size: 10px;
                  white-space: pre-wrap; word-break: break-all; }}
  .stats {{ margin-top: 20px; background: white; padding: 15px; border: 1px solid #ccc; }}
  .stats h2 {{ margin-top: 0; }}
  .stats table {{ border-collapse: collapse; width: 100%; }}
  .stats td, .stats th {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
  .ok {{ color: green; font-weight: bold; }}
  .miss {{ color: red; font-weight: bold; }}
</style>
</head>
<body>
<h1>E2E Diagram Comparison</h1>
<div class="comparison">
  <div class="panel" id="gen-panel">
    <h2>Generated Diagram</h2>
    <div id="gen-content" class="xml-content"></div>
  </div>
  <div class="panel" id="ref-panel">
    <h2>Reference Diagram</h2>
    <div id="ref-content" class="xml-content"></div>
  </div>
</div>
<div class="stats" id="stats"></div>
<script>
  // Display cell summaries
  const genXml = {json.dumps(gen_xml)};
  const refXml = {json.dumps(ref_xml)};

  function extractLabels(xml) {{
    const parser = new DOMParser();
    const doc = parser.parseFromString(xml, 'text/xml');
    const cells = doc.querySelectorAll('mxCell');
    const labels = [];
    cells.forEach(cell => {{
      const val = cell.getAttribute('value') || '';
      const clean = val.replace(/<[^>]+>/g, '').trim();
      if (clean.length > 2) labels.push(clean.substring(0, 80));
    }});
    return labels;
  }}

  const genLabels = extractLabels(genXml);
  const refLabels = extractLabels(refXml);

  document.getElementById('gen-content').textContent =
    'Cells with labels: ' + genLabels.length + '\\n\\n' +
    genLabels.join('\\n');
  document.getElementById('ref-content').textContent =
    'Cells with labels: ' + refLabels.length + '\\n\\n' +
    refLabels.join('\\n');

  const genSet = new Set(genLabels);
  const refSet = new Set(refLabels);
  const both = genLabels.filter(l => refSet.has(l));
  const onlyGen = genLabels.filter(l => !refSet.has(l));
  const onlyRef = refLabels.filter(l => !genSet.has(l));

  document.getElementById('stats').innerHTML = `
    <h2>Label Comparison</h2>
    <table>
      <tr><th>Metric</th><th>Count</th></tr>
      <tr><td>Generated labels</td><td>${{genLabels.length}}</td></tr>
      <tr><td>Reference labels</td><td>${{refLabels.length}}</td></tr>
      <tr><td class="ok">In both</td><td>${{both.length}}</td></tr>
      <tr><td class="miss">Only in generated</td><td>${{onlyGen.length}}</td></tr>
      <tr><td class="miss">Only in reference</td><td>${{onlyRef.length}}</td></tr>
    </table>
    <h3>Only in Generated</h3>
    <ul>${{onlyGen.map(l => '<li>' + l + '</li>').join('')}}</ul>
    <h3>Only in Reference</h3>
    <ul>${{onlyRef.map(l => '<li>' + l + '</li>').join('')}}</ul>
  `;
</script>
</body>
</html>"""
    path = artifact_dir / "comparison.html"
    path.write_text(html, encoding="utf-8")
    return path


def run_visual_comparison():
    """Run visual comparison and capture screenshots."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_dir = PROJECT_ROOT / "artifacts" / "final-comparison" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Visual Comparison Run {run_id} ===\n")

    # Find the latest generated diagram
    gen_dirs = sorted(
        (PROJECT_ROOT / "artifacts" / "final-comparison").iterdir(),
        key=lambda d: d.name,
    )
    gen_file = None
    for d in reversed(gen_dirs):
        candidate = d / "generated_diagram.drawio"
        if candidate.exists():
            gen_file = candidate
            break

    if gen_file is None:
        print("ERROR: No generated diagram found. Run run_e2e_comparison.py first.")
        return

    ref_file = PROJECT_ROOT / "docs" / "CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1).drawio"

    print(f"Generated: {gen_file}")
    print(f"Reference: {ref_file}")

    gen_xml = gen_file.read_text(encoding="utf-8")
    ref_xml = ref_file.read_text(encoding="utf-8")

    gen_root = ET.fromstring(gen_xml)
    ref_root = ET.parse(str(ref_file)).getroot()

    # Semantic comparison
    label_comparison = _compare_labels(gen_root, ref_root)

    # Create HTML viewer
    html_path = _create_viewer_html(gen_xml, ref_xml, artifact_dir)
    print(f"Comparison HTML: {html_path}")

    # Capture screenshots with Playwright
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})

            # Capture the comparison page
            page.goto(f"file:///{html_path.as_posix()}")
            page.wait_for_load_state("networkidle")

            screenshot_path = artifact_dir / "comparison_screenshot.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"Comparison screenshot: {screenshot_path}")

            browser.close()
    except Exception as e:
        print(f"Playwright screenshot failed: {e}")
        print("Comparison HTML still available for manual inspection.")

    # Save detailed comparison report
    report = {
        "run_id": run_id,
        "generated_file": str(gen_file),
        "reference_file": str(ref_file),
        "generated_cell_count": len(list(gen_root.iter("mxCell"))),
        "reference_cell_count": len(list(ref_root.iter("mxCell"))),
        "labels_in_both": len(label_comparison["in_both"]),
        "labels_only_in_generated": len(label_comparison["only_in_generated"]),
        "labels_only_in_reference": len(label_comparison["only_in_reference"]),
        "only_in_generated_samples": label_comparison["only_in_generated"][:20],
        "only_in_reference_samples": label_comparison["only_in_reference"][:20],
    }

    report_path = artifact_dir / "visual_comparison_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {report_path}")

    # Summary
    print(f"\n=== Label Comparison ===")
    print(f"Generated cells: {report['generated_cell_count']}")
    print(f"Reference cells: {report['reference_cell_count']}")
    print(f"Labels in both: {report['labels_in_both']}")
    print(f"Only in generated: {report['labels_only_in_generated']}")
    print(f"Only in reference: {report['labels_only_in_reference']}")
    print(f"\nArtifacts: {artifact_dir}")

    return report


if __name__ == "__main__":
    run_visual_comparison()
