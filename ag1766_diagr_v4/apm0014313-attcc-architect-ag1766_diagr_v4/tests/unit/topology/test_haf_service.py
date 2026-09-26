"""Block 8 — haf service integration: wire extractor + pipeline.

Uses in-memory SQLite with the full synthetic fixture from test_haf_extractor.
Verifies the end-to-end flow from intake_id to filled draw.io XML.

All data is synthetic. No client data is used.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from sqlalchemy.orm import Session

from tests.unit.topology.test_haf_extractor import _seed_synthetic_app


def _test_template() -> bytes:
    """Minimal template matching OUTPOST_V1 profile bindings."""
    return (
        b'<mxfile>'
        b'<diagram id="page1" name="Outpost Topology">'
        b'<mxGraphModel><root>'
        b'<mxCell id="root-0" haf-role="root_layer" />'
        b'<mxCell id="frame-1" parent="root-0" value="" vertex="1" '
        b'  style="fillColor=#FFE6CC;" haf-role="outer_frame">'
        b'<mxGeometry x="0" y="0" width="2000" height="1500" as="geometry"/></mxCell>'
        b'<mxCell id="header-2" parent="root-0" '
        b'  value="AT&amp;T - AWS Alpharetta, GA NEEDS-OUTPOST-ID" '
        b'  vertex="1" haf-role="header_line">'
        b'<mxGeometry x="10" y="10" width="1980" height="40" as="geometry"/></mxCell>'
        b'<mxCell id="subnet-3" parent="root-0" '
        b'  value="Private Application Subnet NEEDS-CIDR&#10;UNRESOLVED-subnet" '
        b'  vertex="1" haf-role="private_application_subnet">'
        b'<mxGeometry x="100" y="200" width="400" height="300" as="geometry"/></mxCell>'
        b'<mxCell id="vpc-5" parent="root-0" '
        b'  value="Workload VPC NEEDS-AZ NEEDS-CIDR" '
        b'  vertex="1" haf-role="workload_vpc">'
        b'<mxGeometry x="80" y="180" width="500" height="400" as="geometry"/></mxCell>'
        # AT&T Internal Interfaces container (required for programmatic generation)
        b'<mxCell id="att-band" parent="root-0" '
        b'  value="" vertex="1" style="fillColor=#DAE8FC;" '
        b'  haf-role="att_internal_interfaces_band">'
        b'<mxGeometry x="-220" y="745" width="385" height="1000" as="geometry"/></mxCell>'
        b'<mxCell id="att-in-10" parent="att-band" '
        b'  value="&lt;None found&gt;" vertex="1" '
        b'  haf-role="att_internal_in_slot">'
        b'<mxGeometry x="1200" y="200" width="200" height="300" as="geometry"/></mxCell>'
        b'<mxCell id="azure-11" parent="root-0" '
        b'  value="&lt;None found&gt;" vertex="1" '
        b'  haf-role="azure_apps_slot">'
        b'<mxGeometry x="1200" y="600" width="200" height="200" as="geometry"/></mxCell>'
        b'<mxCell id="nas-13" parent="root-0" '
        b'  value=" - NAS Server: &#10; - EC2 Names: " vertex="1" '
        b'  haf-role="nas_detail_block">'
        b'<mxGeometry x="900" y="700" width="250" height="80" as="geometry"/></mxCell>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )


class TestHafService:
    """Block 8: end-to-end service wiring."""

    def test_generate_haf_topology(self, tmp_engine):
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)

            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=_test_template(),
            )

        # Should produce filled XML
        assert len(result.filled_xml) > 0
        root = ET.fromstring(result.filled_xml)
        assert root.tag == "mxfile"

        # Interfaces should be populated
        xml_str = result.filled_xml.decode("utf-8")
        assert "ORACLE SCM" in xml_str or "DITREX" in xml_str
        assert "DPG Sales" in xml_str

        # Tokens from DB should be resolved
        assert "10.0.0.0/16" in xml_str  # vpc_cidr
        assert "130.10.20.0/28" in xml_str  # subnet_cidr

        # Some tokens are missing from our fixture — expect gaps
        assert len(result.gaps) > 0

    def test_service_returns_extraction_issues(self, tmp_engine):
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)

            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=_test_template(),
            )

        # Should report extraction issues for tokens without DB answers
        assert len(result.extraction_issues) > 0

    def test_service_mutations_are_tracked(self, tmp_engine):
        from migration_intake.topology.haf_service import generate_haf_topology

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)

            result = generate_haf_topology(
                session=session,
                intake_id=intake_id,
                profile_id="OUTPOST_V1",
                template_bytes=_test_template(),
            )

        assert len(result.mutations) > 0
        # Must include interface fills and token resolutions
        mutation_types = {m.token for m in result.mutations}
        assert any("interface" in t for t in mutation_types)
