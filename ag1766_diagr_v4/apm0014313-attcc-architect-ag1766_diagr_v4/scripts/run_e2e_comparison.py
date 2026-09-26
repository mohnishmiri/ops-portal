"""E2E comparison: generate diagram from input template vs architect's reference.

This script:
1. Runs the full topology pipeline using the input template + synthetic DB data
2. Saves the generated diagram
3. Performs semantic comparison against the architect's final reference
4. Produces a detailed report

Usage: python scripts/run_e2e_comparison.py
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

INPUT_TEMPLATE = PROJECT_ROOT / "docs" / "input_CCPM_AWS_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
REFERENCE_FILE = PROJECT_ROOT / "docs" / "CCPM__FINAL_18678_TargetState_AWS_OutPosts_v01 (1).drawio"
MASTER_TEMPLATE = PROJECT_ROOT / "docs" / "AWS_Outpost_Topology_Template_1-v1.7.drawio"
DEV_TEMPLATE = PROJECT_ROOT / "docs" / "development" / "topo_9_24" / "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_sections(root: ET.Element) -> dict:
    """Extract structural information from a draw.io XML."""
    sections = {}
    for cell in root.iter("mxCell"):
        role = cell.get("haf-role", "")
        cid = cell.get("id", "")
        value = _strip_html(cell.get("value", ""))
        style = cell.get("style", "")
        geom = cell.find("mxGeometry")
        geo = {}
        if geom is not None:
            geo = {
                "x": geom.get("x"),
                "y": geom.get("y"),
                "width": geom.get("width"),
                "height": geom.get("height"),
            }
        sections[cid] = {
            "role": role,
            "value": value[:200],
            "style_prefix": style[:80],
            "geometry": geo,
        }
    return sections


def _find_labeled_cells(root: ET.Element, pattern: str) -> list[dict]:
    """Find cells whose value contains a pattern."""
    results = []
    for cell in root.iter("mxCell"):
        val = _strip_html(cell.get("value", ""))
        if pattern.lower() in val.lower():
            results.append({
                "id": cell.get("id", ""),
                "role": cell.get("haf-role", ""),
                "value": val[:200],
            })
    return results


def run_comparison():
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_dir = PROJECT_ROOT / "artifacts" / "final-comparison" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== E2E Comparison Run {run_id} ===\n")

    # Load templates
    if not INPUT_TEMPLATE.exists():
        print(f"ERROR: Input template not found: {INPUT_TEMPLATE}")
        return
    if not REFERENCE_FILE.exists():
        print(f"ERROR: Reference file not found: {REFERENCE_FILE}")
        return

    # Use bundled annotated template (Tab 0 — "Without LBs")
    from migration_intake.topology.template_loader import load_bundled_template
    template_bytes = load_bundled_template("basic")
    ref_root = ET.parse(str(REFERENCE_FILE)).getroot()

    # Run the pipeline with synthetic data (no DB — use the pipeline directly)
    from migration_intake.topology.interface_normalization import (
        create_interface_candidate,
        group_interfaces_by_protocol_family,
    )
    from migration_intake.topology.haf_pipeline import fill_haf_template

    # Synthetic CCPM-like data
    tokens = {
        "outpost_id": "op-0123456789abcdef0",
        "vpc_cidr": "10.0.0.0/16",
        "subnet_cidr": "130.10.20.0/28",
        "subnet_name": "private-app-subnet-1",
        "app_sg_name": "ccpm-app-sg",
        "aws_account_id": "123456789012",
        "availability_zone": "us-east-1a",
        "db_sg_name": "ccpm-db-sg",
    }

    # Synthetic interfaces matching CCPM patterns
    candidates = [
        create_interface_candidate(
            interface_system_location="ATT", data_traffic_direction="Inbound",
            target_protocol="HTTPS(TLSv1.2)", future_port="443",
            interface_app_acronym="ORACLE SCM", interface_correlation_id="18249",
        ),
        create_interface_candidate(
            interface_system_location="ATT", data_traffic_direction="Inbound",
            target_protocol="JDBC over TLS 1.2", future_port="1521",
            interface_app_acronym="DITREX", interface_correlation_id="18274",
        ),
        create_interface_candidate(
            interface_system_location="Midrange", data_traffic_direction="Outbound",
            target_protocol="SFTP using OpenSSH", future_port="22",
            interface_app_acronym="LS-OMS", interface_correlation_id="10038",
        ),
        create_interface_candidate(
            interface_system_location="Midrange", data_traffic_direction="Outbound",
            target_protocol="HTTPS(TLSv1.2)", future_port="443",
            interface_app_acronym="MyTracker", interface_correlation_id="19166",
        ),
        create_interface_candidate(
            interface_system_location="Midrange", data_traffic_direction="Outbound",
            target_protocol="ODBC(TCPS)", future_port="1433",
            interface_app_acronym="DVT", interface_correlation_id="30358",
        ),
        create_interface_candidate(
            interface_system_location="Azure", data_traffic_direction="Outbound",
            target_protocol="HTTPS(TLSv1.2)", future_port="443",
            interface_app_acronym="DPG Sales", interface_correlation_id="31479",
        ),
        create_interface_candidate(
            interface_system_location="Azure", data_traffic_direction="Outbound",
            target_protocol="HTTPS", future_port="443",
            interface_app_acronym="AZDP", interface_correlation_id="30333",
        ),
        # AWS interfaces for Tier 1
        create_interface_candidate(
            interface_system_location="AWS", data_traffic_direction="Inbound",
            target_protocol="HTTPS(TLSv1.2)", future_port="443",
            interface_app_acronym="DTV-VDAS", interface_correlation_id="32387",
        ),
    ]

    interface_groups = group_interfaces_by_protocol_family(candidates, category_filter="INTERNAL")
    aws_interface_groups = group_interfaces_by_protocol_family(
        candidates,
        category_filter="AWS",
        direction_filter=frozenset({"INBOUND", "BIDIRECTIONAL"}),
    )

    # Build legacy interfaces dict
    interfaces: dict[str, list[dict]] = {}
    for c in candidates:
        key = f"{c.norm_category}:{c.norm_direction}"
        interfaces.setdefault(key, []).append({
            "app_name": c.interface_app_acronym or "",
            "correlation_id": c.interface_correlation_id or "",
        })

    details = {}

    result = fill_haf_template(
        template_bytes=template_bytes,
        tokens=tokens,
        interfaces=interfaces,
        details=details,
        profile_id="OUTPOST_V1_BASIC",
        interface_groups=interface_groups,
        aws_interface_groups=aws_interface_groups,
    )

    # Save generated diagram
    generated_path = artifact_dir / "generated_diagram.drawio"
    generated_path.write_bytes(result.filled_xml)
    print(f"Generated diagram: {generated_path}")

    # Parse generated
    gen_root = ET.fromstring(result.filled_xml)

    # === Semantic Comparison ===
    report = {
        "run_id": run_id,
        "generated_path": str(generated_path),
        "reference_path": str(REFERENCE_FILE),
        "template_path": "bundled:basic (Without LBs)",
        "pipeline_success": result.success,
        "mutations_count": len(result.mutations),
        "gaps_count": len(result.gaps),
        "gaps": [{"role": g.haf_role, "token": g.token, "pattern": g.pattern, "blocking": g.blocking} for g in result.gaps],
    }

    # 1. Check generated sections
    gen_sections = _extract_sections(gen_root)
    ref_sections = _extract_sections(ref_root)

    report["generated_cell_count"] = len(gen_sections)
    report["reference_cell_count"] = len(ref_sections)

    # 2. Check ATT Internal generated content
    att_gen_cells = [cid for cid in gen_sections if cid.startswith("att_internal_gen_")]
    report["att_internal_generated_cells"] = len(att_gen_cells)

    # 3. Check AWS Tier 1 generated content
    aws_gen_cells = [cid for cid in gen_sections if cid.startswith("aws_tier1_gen_")]
    report["aws_tier1_generated_cells"] = len(aws_gen_cells)

    # 4. Check AWS Tier 1 container preserved
    aws_containers = _find_labeled_cells(gen_root, "Tier 1")
    report["aws_tier1_container_present"] = len(aws_containers) > 0

    # 5. Check static sections preserved
    static_sections = [
        "GitHub Runners", "JFrog", "DNS", "AWS Home Region",
        "DirectConnect", "Conexus", "Tier 2", "Internet",
        "SMTP", "CloudWatch",
    ]
    preserved = {}
    for section in static_sections:
        found = _find_labeled_cells(gen_root, section)
        preserved[section] = len(found) > 0
    report["static_sections_preserved"] = preserved

    # 6. Check tokens resolved
    gen_xml = result.filled_xml.decode("utf-8")
    unresolved = []
    for pattern in ["NEEDS-", "UNRESOLVED-", "ACC-"]:
        if pattern in gen_xml:
            count = gen_xml.count(pattern)
            unresolved.append(f"{pattern} ({count} occurrences)")
    report["unresolved_patterns"] = unresolved

    # 7. Interface data comparison
    ref_interface_data = _find_labeled_cells(ref_root, "DTV-VDAS")
    gen_interface_data = _find_labeled_cells(gen_root, "DTV-VDAS")
    report["reference_has_dtv_vdas"] = len(ref_interface_data) > 0
    report["generated_has_dtv_vdas"] = len(gen_interface_data) > 0

    ref_oracle_scm = _find_labeled_cells(ref_root, "ORACLE SCM")
    gen_oracle_scm = _find_labeled_cells(gen_root, "ORACLE SCM")
    report["reference_has_oracle_scm"] = len(ref_oracle_scm) > 0
    report["generated_has_oracle_scm"] = len(gen_oracle_scm) > 0

    # 8. Color/family comparison
    att_families = set()
    for g in interface_groups:
        att_families.add(g.family)
    aws_families = set()
    for g in aws_interface_groups:
        aws_families.add(g.family)
    report["att_internal_families"] = sorted(att_families)
    report["aws_tier1_families"] = sorted(aws_families)

    # 9. Known differences
    known_diffs = []
    # AWS Tier 1 in reference has manually drawn connectors to VPCE nodes
    # Our generator creates connectors that exit the container but don't target specific nodes
    known_diffs.append("AWS Tier 1 connectors: reference targets VPCE nodes; generated exits container boundary")
    # Reference has specific NLB icons and connectors we don't generate
    known_diffs.append("NLB and security group internal connectors: static in reference, not generated by our pipeline")
    # Reference ATT Internal has different visual grouping
    known_diffs.append("ATT Internal layout: reference uses manually placed entries; generated uses automated layout")
    report["known_differences"] = known_diffs

    # Save report
    report_path = artifact_dir / "comparison_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Comparison report: {report_path}")

    # Print summary
    print(f"\n=== Summary ===")
    print(f"Pipeline success: {result.success}")
    print(f"Mutations: {len(result.mutations)}")
    print(f"Gaps: {len(result.gaps)}")
    print(f"ATT Internal generated cells: {len(att_gen_cells)}")
    print(f"AWS Tier 1 generated cells: {len(aws_gen_cells)}")
    print(f"AWS Tier 1 container present: {report['aws_tier1_container_present']}")
    print(f"DTV-VDAS in reference: {report['reference_has_dtv_vdas']}")
    print(f"DTV-VDAS in generated: {report['generated_has_dtv_vdas']}")
    print(f"ORACLE SCM in reference: {report['reference_has_oracle_scm']}")
    print(f"ORACLE SCM in generated: {report['generated_has_oracle_scm']}")
    print(f"ATT Internal families: {report['att_internal_families']}")
    print(f"AWS Tier 1 families: {report['aws_tier1_families']}")
    print(f"\nStatic sections preserved:")
    for section, ok in preserved.items():
        status = "OK" if ok else "MISSING"
        print(f"  {section}: {status}")
    if unresolved:
        print(f"\nUnresolved patterns remaining:")
        for u in unresolved:
            print(f"  {u}")
    print(f"\nKnown differences:")
    for d in known_diffs:
        print(f"  - {d}")
    print(f"\nArtifacts: {artifact_dir}")

    return report


if __name__ == "__main__":
    run_comparison()
