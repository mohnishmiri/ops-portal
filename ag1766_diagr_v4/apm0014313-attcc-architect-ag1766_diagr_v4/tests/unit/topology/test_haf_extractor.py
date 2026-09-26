"""Block 7 — haf_extractor: extract tokens/interfaces/details from DB.

All data is synthetic. No client data is used.
Uses in-memory SQLite via the existing conftest.py tmp_engine fixture.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    ApplicationIdentifier,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)
from migration_intake.persistence.models_interfaces import InterfaceRecord


def _now():
    return datetime.now(UTC)


def _uuid():
    return str(uuid.uuid4())


def _seed_synthetic_app(session: Session, *, include_aws_interfaces: bool = False):
    """Seed a synthetic CCPM-like application with answers and interfaces."""
    actor_id = _uuid()
    app_id = _uuid()
    intake_id = _uuid()
    catalog_id = _uuid()
    section_id = _uuid()

    session.add(Actor(id=actor_id, display_name="Synthetic Actor", created_at=_now()))
    session.flush()

    session.add(Application(
        id=app_id,
        state="ACTIVE",
        display_name="CCPM Test App",
        created_at=_now(),
        updated_at=_now(),
        row_version=1,
        interface_epoch=1,
        created_by_id=actor_id,
    ))
    session.flush()

    # Add identifiers
    session.add(ApplicationIdentifier(
        id=_uuid(),
        application_id=app_id,
        identifier_type="CORRELATION",
        raw_value="18678",
        normalized_value="18678",
        created_at=_now(),
    ))
    session.flush()

    # Add catalog
    session.add(CatalogRelease(
        id=catalog_id,
        semantic_version="1.0.0",
        source_filename="synthetic.yaml",
        source_sha256="a" * 64,
        compiler_version="1.0.0",
        pub_state="PUBLISHED",
        catalog_hash="b" * 64,
        created_at=_now(),
    ))
    session.flush()

    session.add(CatalogSection(
        id=section_id,
        release_id=catalog_id,
        section_code="NET",
        display_name="Network",
        display_order=1,
    ))
    session.flush()

    # Add intake
    session.add(Intake(
        id=intake_id,
        application_id=app_id,
        catalog_id=catalog_id,
        state="ACTIVE",
        created_at=_now(),
        updated_at=_now(),
        row_version=1,
        content_epoch=1,
        created_by_id=actor_id,
    ))
    session.flush()

    # Add questions and answers for topology tokens
    _add_answer(session, intake_id, section_id, actor_id,
                "VPC_CIDR", "10.0.0.0/16")
    _add_answer(session, intake_id, section_id, actor_id,
                "SUBNET_CIDR", "130.10.20.0/28")

    # Add interface records
    _add_interface(session, app_id, actor_id,
                   correlation_id="18249", acronym="ORACLE SCM",
                   location="ATT", direction="Inbound")
    _add_interface(session, app_id, actor_id,
                   correlation_id="18274", acronym="DITREX",
                   location="ATT", direction="Inbound")
    _add_interface(session, app_id, actor_id,
                   correlation_id="31479", acronym="DPG Sales",
                   location="Azure", direction="Outbound")

    if include_aws_interfaces:
        _add_interface(session, app_id, actor_id,
                       correlation_id="32387", acronym="DTV-VDAS",
                       location="AWS", direction="Inbound",
                       protocol="HTTPS(TLSv1.2)", port="443")
        _add_interface(session, app_id, actor_id,
                       correlation_id="32388", acronym="BILLING-SVC",
                       location="AWS", direction="Inbound",
                       protocol="JDBC over TLS 1.2", port="1521")

    session.commit()
    return app_id, intake_id


def _add_answer(session, intake_id, section_id, actor_id,
                question_code, value_text):
    q_id = _uuid()
    inst_id = _uuid()
    rev_id = _uuid()

    session.add(CatalogQuestion(
        id=q_id,
        section_id=section_id,
        question_code=question_code,
        question_text=f"What is the {question_code}?",
        response_type="FREE_TEXT",
        required_level="REQUIRED",
        collection_mode="STANDARD",
        display_order=1,
    ))
    session.flush()

    session.add(AnswerInstance(
        id=inst_id,
        intake_id=intake_id,
        question_id=q_id,
        current_rev_id=None,
        created_at=_now(),
        updated_at=_now(),
    ))
    session.flush()

    session.add(AnswerRevision(
        id=rev_id,
        instance_id=inst_id,
        revision_number=1,
        response_json=json.dumps({"value": value_text}),
        confirm_state="CONFIRMED",
        authored_at=_now(),
        authored_by_id=actor_id,
    ))
    session.flush()

    # Set current_rev_id after creating the revision (break circular FK)
    inst = session.get(AnswerInstance, inst_id)
    inst.current_rev_id = rev_id
    session.flush()


def _add_interface(session, app_id, actor_id, *,
                   correlation_id, acronym, location, direction,
                   protocol=None, port=None):
    session.add(InterfaceRecord(
        id=_uuid(),
        application_id=app_id,
        migrating_app_correlation_id="18678",
        migrating_app_acronym="CCPM",
        interface_correlation_id=correlation_id,
        interface_app_acronym=acronym,
        interface_system_location=location,
        data_traffic_direction=direction,
        target_protocol=protocol,
        future_port=port,
        state="ACTIVE",
        origin="IMPORT",
        created_at=_now(),
        created_by_id=actor_id,
        updated_at=_now(),
        updated_by_id=actor_id,
    ))
    session.flush()


class TestHafExtractor:
    """Block 7: extract tokens, interfaces, and details from the DB."""

    def test_extract_tokens_from_answers(self, tmp_engine):
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        assert result.tokens["vpc_cidr"] == "10.0.0.0/16"
        assert result.tokens["subnet_cidr"] == "130.10.20.0/28"

    def test_extract_correlation_id_from_identifiers(self, tmp_engine):
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        assert result.tokens.get("correlation_id") == "18678"

    def test_extract_interfaces_grouped(self, tmp_engine):
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        # ATT inbound interfaces
        att_in = result.interfaces.get("INTERNAL:INBOUND", [])
        assert len(att_in) == 2
        names = {i["app_name"] for i in att_in}
        assert "ORACLE SCM" in names
        assert "DITREX" in names

    def test_extract_azure_interfaces(self, tmp_engine):
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        azure = result.interfaces.get("AZURE:OUTBOUND", [])
        assert len(azure) == 1
        assert azure[0]["app_name"] == "DPG Sales"

    def test_missing_answers_listed_in_issues(self, tmp_engine):
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = _seed_synthetic_app(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        # We only seeded VPC_CIDR and SUBNET_CIDR, so outpost_id, etc. are missing
        assert len(result.issues) > 0  # at least some missing tokens


class TestHafExtractorGuideLocations:
    """Test guide-required location values for ATT Internal section.

    Per Topology Guide: Midrange/Hybrid/Private/Conexus/OnPrem should be
    classified as INTERNAL for the AT&T Internal Interfaces section.
    """

    def _seed_app_with_guide_locations(self, session: Session):
        """Seed app with interfaces using guide-required location values."""
        actor_id = _uuid()
        app_id = _uuid()
        intake_id = _uuid()
        catalog_id = _uuid()
        section_id = _uuid()

        session.add(Actor(id=actor_id, display_name="Guide Test Actor", created_at=_now()))
        session.flush()

        session.add(Application(
            id=app_id,
            state="ACTIVE",
            display_name="Guide Test App",
            created_at=_now(),
            updated_at=_now(),
            row_version=1,
            interface_epoch=1,
            created_by_id=actor_id,
        ))
        session.flush()

        session.add(CatalogRelease(
            id=catalog_id,
            semantic_version="1.0.0",
            source_filename="synthetic.yaml",
            source_sha256="a" * 64,
            compiler_version="1.0.0",
            pub_state="PUBLISHED",
            catalog_hash="b" * 64,
            created_at=_now(),
        ))
        session.flush()

        session.add(CatalogSection(
            id=section_id,
            release_id=catalog_id,
            section_code="NET",
            display_name="Network",
            display_order=1,
        ))
        session.flush()

        session.add(Intake(
            id=intake_id,
            application_id=app_id,
            catalog_id=catalog_id,
            state="ACTIVE",
            created_at=_now(),
            updated_at=_now(),
            row_version=1,
            content_epoch=1,
            created_by_id=actor_id,
        ))
        session.flush()

        # Add interfaces with guide-required location values
        _add_interface(session, app_id, actor_id,
                       correlation_id="11111", acronym="MIDRANGE APP",
                       location="Midrange", direction="IN",
                       protocol="JDBC", port="1521")
        _add_interface(session, app_id, actor_id,
                       correlation_id="22222", acronym="HYBRID APP",
                       location="Hybrid", direction="OUT",
                       protocol="HTTP", port="8080")
        _add_interface(session, app_id, actor_id,
                       correlation_id="33333", acronym="PRIVATE APP",
                       location="Private", direction="IN/OUT",
                       protocol="HTTPS", port="443")
        _add_interface(session, app_id, actor_id,
                       correlation_id="44444", acronym="CONEXUS APP",
                       location="Conexus", direction="Inbound",
                       protocol="SQL", port="1433")
        _add_interface(session, app_id, actor_id,
                       correlation_id="55555", acronym="ONPREM APP",
                       location="OnPrem", direction="Outbound",
                       protocol="TCP", port="22")

        session.commit()
        return app_id, intake_id

    def test_midrange_classified_as_internal(self, tmp_engine):
        """Midrange location should be classified as INTERNAL."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        # Check legacy interface dict
        internal_in = result.interfaces.get("INTERNAL:INBOUND", [])
        names = {i["app_name"] for i in internal_in}
        assert "MIDRANGE APP" in names

    def test_hybrid_classified_as_internal(self, tmp_engine):
        """Hybrid location should be classified as INTERNAL."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        internal_out = result.interfaces.get("INTERNAL:OUTBOUND", [])
        names = {i["app_name"] for i in internal_out}
        assert "HYBRID APP" in names

    def test_private_classified_as_internal(self, tmp_engine):
        """Private location should be classified as INTERNAL."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        internal_bidir = result.interfaces.get("INTERNAL:BIDIRECTIONAL", [])
        names = {i["app_name"] for i in internal_bidir}
        assert "PRIVATE APP" in names

    def test_conexus_classified_as_internal(self, tmp_engine):
        """Conexus location should be classified as INTERNAL."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        internal_in = result.interfaces.get("INTERNAL:INBOUND", [])
        names = {i["app_name"] for i in internal_in}
        assert "CONEXUS APP" in names

    def test_onprem_classified_as_internal(self, tmp_engine):
        """OnPrem location should be classified as INTERNAL."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        internal_out = result.interfaces.get("INTERNAL:OUTBOUND", [])
        names = {i["app_name"] for i in internal_out}
        assert "ONPREM APP" in names

    def test_interface_groups_created_for_internal(self, tmp_engine):
        """Interface groups should be created for INTERNAL interfaces."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        # Should have groups for each unique protocol family
        assert len(result.interface_groups) > 0

        # Check that groups are ProtocolFamilyGroup instances (have 'family' attr)
        for g in result.interface_groups:
            assert hasattr(g, "family"), "interface_groups should be ProtocolFamilyGroup"

    def test_interface_groups_are_protocol_family_type(self, tmp_engine):
        """Extractor should return ProtocolFamilyGroup objects."""
        from migration_intake.topology.haf_extractor import extract_haf_data
        from migration_intake.topology.interface_normalization import ProtocolFamilyGroup

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        for g in result.interface_groups:
            assert isinstance(g, ProtocolFamilyGroup)
        # Guide-location interfaces seed 5 different protocols:
        # JDBC→ORACLE_DB, HTTP→HTTPS, HTTPS→HTTPS, SQL→SQL_DB, TCP→OTHER
        families = {g.family for g in result.interface_groups}
        assert "ORACLE_DB" in families  # JDBC
        assert "HTTPS" in families  # HTTP + HTTPS merged

    def test_interface_candidates_created(self, tmp_engine):
        """Interface candidates should be created for all interfaces."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        # Should have 5 candidates (one for each interface)
        assert len(result.interface_candidates) == 5

        # All should be classified as INTERNAL
        internal_count = sum(
            1 for c in result.interface_candidates
            if c.norm_category == "INTERNAL"
        )
        assert internal_count == 5

    def test_normalization_report_created(self, tmp_engine):
        """Normalization report should be created with correct counts."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        assert result.normalization_report is not None
        assert result.normalization_report.total_processed == 5
        assert result.normalization_report.internal_valid == 5
        assert result.normalization_report.excluded_by_category == 0

    def test_bidirectional_direction_normalized(self, tmp_engine):
        """IN/OUT direction should be normalized to BIDIRECTIONAL."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        # Find the PRIVATE APP candidate (has IN/OUT direction)
        private_candidate = next(
            c for c in result.interface_candidates
            if c.interface_app_acronym == "PRIVATE APP"
        )
        assert private_candidate.norm_direction == "BIDIRECTIONAL"

    def test_protocol_port_in_candidates(self, tmp_engine):
        """Protocol and port should be captured in candidates."""
        from migration_intake.topology.haf_extractor import extract_haf_data

        with Session(tmp_engine) as session:
            app_id, intake_id = self._seed_app_with_guide_locations(session)
            result = extract_haf_data(session, intake_id, "OUTPOST_V1")

        # Find the MIDRANGE APP candidate
        midrange_candidate = next(
            c for c in result.interface_candidates
            if c.interface_app_acronym == "MIDRANGE APP"
        )
        assert midrange_candidate.norm_protocol == "JDBC"
        assert midrange_candidate.norm_port == "1521"
