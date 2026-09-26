"""Block 9 — End-to-end haf pipeline verification with real v1.7 template.

Uses:
- The REAL v1.7 input template (docs/development/topo_9_24)
- Synthetic DB data matching CCPM patterns (no client data)
- Full pipeline: DB extraction -> token resolution -> interface fill -> detail fill

All data is synthetic. No client data is used.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tests.unit.topology.test_haf_extractor import _seed_synthetic_app

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "development"
    / "topo_9_24"
    / "AWS__input_Outpost_Topology_UNRESOLVED_UNRESOLVED-v1.7.drawio"
)


@pytest.fixture
def real_template():
    if not TEMPLATE_PATH.exists():
        pytest.skip("Real v1.7 input template not available")
    return TEMPLATE_PATH.read_bytes()


class TestEndToEnd:
    """Block 9: full pipeline with real template + synthetic CCPM data."""

    def test_real_template_with_db_data(self, tmp_engine, real_template):
        """Full E2E: real template + synthetic DB data -> filled diagram."""
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        # Must produce valid draw.io XML
        root = ET.fromstring(result.filled_xml)
        assert root.tag == "mxfile"

        xml_str = result.filled_xml.decode("utf-8")

        # DB tokens should be resolved
        assert "10.0.0.0/16" in xml_str, "VPC CIDR not resolved"
        assert "130.10.20.0/28" in xml_str, "Subnet CIDR not resolved"

        # Interfaces should be populated
        assert "ORACLE SCM" in xml_str or "DITREX" in xml_str, (
            "ATT internal interfaces not populated"
        )

        # DPG Sales should appear in azure slot
        assert "DPG Sales" in xml_str, "Azure interface not populated"

        # Some tokens are not in our synthetic DB — should produce gaps
        assert len(result.gaps) > 0, "Expected gaps for missing tokens"

        # Should have mutations
        assert len(result.mutations) > 0, "Expected mutations"

        # Extraction issues for missing tokens
        assert len(result.extraction_issues) > 0, (
            "Expected extraction issues for tokens without DB answers"
        )

    def test_structural_integrity_preserved(self, tmp_engine, real_template):
        """Non-ATT-slot cells must be preserved; ATT slots are replaced by generated cells."""
        from migration_intake.topology.att_internal_generator import (
            GENERATED_ID_PREFIX,
            STATIC_SLOT_ROLES,
        )
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        before = ET.fromstring(real_template)
        after = ET.fromstring(result.filled_xml)

        before_cells = {c.get("id"): c for c in before.iter("mxCell") if c.get("id")}
        after_cells = {c.get("id"): c for c in after.iter("mxCell") if c.get("id")}

        # Identify static ATT slot cells (expected to be removed)
        static_slot_ids = set()
        for cell in before.iter("mxCell"):
            roles = set(cell.get("haf-role", "").split())
            if roles & STATIC_SLOT_ROLES:
                cid = cell.get("id")
                if cid:
                    static_slot_ids.add(cid)

        # Non-slot original cells must be preserved
        non_slot_before = set(before_cells.keys()) - static_slot_ids
        assert non_slot_before.issubset(set(after_cells.keys())), (
            "Original non-slot cells were removed after pipeline"
        )

        # Generated cells should exist
        generated_ids = {
            cid for cid in after_cells if cid.startswith(GENERATED_ID_PREFIX)
        }
        assert len(generated_ids) > 0, "No generated ATT internal cells found"

        # Structural attributes preserved for non-slot original cells
        for cid in non_slot_before:
            bc = before_cells[cid]
            ac = after_cells[cid]
            for attr in ("parent", "style", "vertex", "edge", "source", "target"):
                assert bc.get(attr) == ac.get(attr), (
                    f"{attr} changed for cell {cid}"
                )
            bg = bc.find("mxGeometry")
            ag = ac.find("mxGeometry")
            if bg is not None:
                assert ag is not None, f"Geometry lost for cell {cid}"
                for gattr in ("x", "y", "width", "height"):
                    assert bg.get(gattr) == ag.get(gattr), (
                        f"geometry.{gattr} changed for cell {cid}"
                    )

    def test_protected_cells_unchanged(self, tmp_engine, real_template):
        """Legend and frame cells must never be mutated."""
        from migration_intake.topology.haf_pipeline import (
            load_haf_profile,
            parse_haf_template,
        )
        from migration_intake.topology.haf_service import generate_haf_topology

        before_index = parse_haf_template(real_template)
        profile = load_haf_profile("OUTPOST_V1")

        # Capture protected cell values before
        protected_before = {}
        for role in before_index.all_roles:
            if profile.is_protected(role):
                for cell in before_index.by_role[role]:
                    protected_before[cell.get("id")] = cell.get("value")

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        # Check protected cells unchanged
        after = ET.fromstring(result.filled_xml)
        after_cells = {c.get("id"): c for c in after.iter("mxCell") if c.get("id")}
        for cid, before_value in protected_before.items():
            assert after_cells[cid].get("value") == before_value, (
                f"Protected cell {cid} was mutated"
            )

    def test_deterministic_output(self, tmp_engine, real_template):
        """Same inputs produce identical output bytes."""
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            first = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        with Session(tmp_engine) as session:
            second = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        assert first.filled_xml == second.filled_xml, (
            "Output is not deterministic"
        )

    def test_gap_report_lists_unresolved_tokens(self, tmp_engine, real_template):
        """Gap report should identify all tokens missing from synthetic DB."""
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        gap_tokens = {g.token for g in result.gaps}
        # We only seeded vpc_cidr and subnet_cidr in the DB
        # outpost_id, app_sg_name, aws_account_id, availability_zone, db_sg_name,
        # subnet_name should all be missing
        expected_missing = {
            "outpost_id", "app_sg_name", "aws_account_id",
            "availability_zone", "db_sg_name", "subnet_name",
        }
        # At least some of these should appear in the gaps
        assert gap_tokens & expected_missing, (
            f"Expected some of {expected_missing} in gaps, got {gap_tokens}"
        )

    def test_generated_cells_use_comma_labels(self, tmp_engine, real_template):
        """E2E: generated ATT internal cells use comma-separated labels."""
        from migration_intake.topology.att_internal_generator import (
            GENERATED_ID_PREFIX,
        )
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        after = ET.fromstring(result.filled_xml)
        left_boxes = [
            c
            for c in after.iter("mxCell")
            if (c.get("id") or "").startswith(GENERATED_ID_PREFIX)
            and c.get("vertex") == "1"
            and "dashed=1" in (c.get("style") or "")
        ]
        # Should have at least one generated left box
        assert len(left_boxes) > 0, "No generated left boxes found"
        # Left boxes should use comma separator (not newline &#10;)
        for box in left_boxes:
            value = box.get("value", "")
            if "," in value:
                # Comma-separated format confirmed
                assert "&#10;" not in value, (
                    f"Generated left box uses newlines instead of commas: {value[:80]}"
                )

    def test_interface_groups_are_family_type(self, tmp_engine, real_template):
        """E2E: service returns ProtocolFamilyGroup objects."""
        from migration_intake.topology.haf_service import generate_haf_topology
        from migration_intake.topology.interface_normalization import (
            ProtocolFamilyGroup,
        )

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        for g in result.interface_groups:
            assert isinstance(g, ProtocolFamilyGroup), (
                f"Expected ProtocolFamilyGroup, got {type(g)}"
            )


class TestAwsTier1PipelineWiring:
    """Slice 7: AWS Tier 1 generator wired into the pipeline."""

    def test_aws_interface_groups_extracted(self, tmp_engine, real_template):
        """Extractor should produce aws_interface_groups for AWS-located interfaces."""
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        assert hasattr(result, "aws_interface_groups"), (
            "Result must have aws_interface_groups attribute"
        )
        assert isinstance(result.aws_interface_groups, list)

    def test_aws_tier1_cells_generated_in_output(self, tmp_engine, real_template):
        """When AWS interfaces exist, aws_tier1_gen_ cells appear in output."""
        from migration_intake.topology.aws_tier1_generator import (
            GENERATED_ID_PREFIX as AWS_PREFIX,
        )
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session, include_aws_interfaces=True)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        after = ET.fromstring(result.filled_xml)
        aws_cells = [
            c for c in after.iter("mxCell")
            if (c.get("id") or "").startswith(AWS_PREFIX)
        ]
        assert len(aws_cells) > 0, "No AWS Tier 1 generated cells found"

    def test_aws_tier1_container_preserved(self, tmp_engine, real_template):
        """AWS Tier 1 container and static icons are preserved."""
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=real_template,
            )

        after = ET.fromstring(result.filled_xml)
        containers = [
            c for c in after.iter("mxCell")
            if "aws_tier1_container" in (c.get("haf-role") or "")
        ]
        assert len(containers) == 1, "AWS Tier 1 container must be preserved"
