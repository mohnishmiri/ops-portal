"""Topology persistence models for legacy and governed generation records."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from migration_intake.persistence.naming import Base
from migration_intake.persistence.types import (
    CanonicalJSON,
    PortableUTC,
    PortableUUID,
    Sha256Hex,
)

__all__ = [
    "GeneratedArtifact",
    "GenerationReservation",
    "GenerationRun",
    "TopologyBaseArtifact",
    "TopologyCapture",
    "TopologyCompatibility",
    "TopologyInput",
    "TopologyReview",
]


class TopologyBaseArtifact(Base):
    __tablename__ = "topo_base"

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    filename: Any = Column(String(255), nullable=False)
    mime_type: Any = Column(String(100), nullable=False)
    size_bytes: Any = Column(Integer, nullable=False)
    sha256_hex: Any = Column(Sha256Hex(), nullable=False)
    content_address: Any = Column(String(255), nullable=False)
    environment: Any = Column(String(32), nullable=True)
    site: Any = Column(String(64), nullable=True)
    variant: Any = Column(String(32), nullable=True, default="default")
    review_state: Any = Column(String(32), nullable=False, default="DRAFT")
    uploaded_by_id: Any = Column(PortableUUID(), nullable=False)
    uploaded_at: Any = Column(PortableUTC(), nullable=False)
    created_at: Any = Column(PortableUTC(), nullable=False)
    row_version: Any = Column(Integer, nullable=False, default=1)
    authority: Any = Column(String(32), nullable=False, default="LEGACY_UNPINNED")
    lifecycle: Any = Column(String(32), nullable=False, default="HISTORICAL")
    profile_id: Any = Column(String(128), nullable=True)
    profile_version: Any = Column(String(32), nullable=True)
    profile_hash: Any = Column(Sha256Hex(), nullable=True)
    template_release_id: Any = Column(PortableUUID(), nullable=True)
    capability: Any = Column(String(32), nullable=True)
    selection_json: Any = Column(CanonicalJSON(), nullable=True)
    selection_hash: Any = Column(Sha256Hex(), nullable=True)
    compatibility_id: Any = Column(PortableUUID(), nullable=True)
    reviewed_by_id: Any = Column(PortableUUID(), nullable=True)
    reviewed_at: Any = Column(PortableUTC(), nullable=True)
    review_rationale: Any = Column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["application_id"], ["applications.id"], name="fk_tpbs_app"),
        ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_tpbs_int"),
        ForeignKeyConstraint(["uploaded_by_id"], ["actors.id"], name="fk_tpbs_act"),
        ForeignKeyConstraint(
            ["template_release_id"], ["tpl_releases.id"], name="fk_tpbs_tpl"
        ),
        Index("ix_tpbs_intake", "intake_id"),
        Index("ix_tpbs_sha", "sha256_hex"),
    )


class GenerationRun(Base):
    __tablename__ = "gen_runs"

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    snapshot_id: Any = Column(PortableUUID(), nullable=True)
    snapshot_sha256: Any = Column(Sha256Hex(), nullable=True)
    catalog_sha256: Any = Column(Sha256Hex(), nullable=True)
    base_artifact_id: Any = Column(PortableUUID(), nullable=False)
    base_sha256: Any = Column(Sha256Hex(), nullable=False)
    config_version: Any = Column(String(32), nullable=True)
    config_sha256: Any = Column(Sha256Hex(), nullable=True)
    status: Any = Column(String(32), nullable=False, default="PENDING")
    error_message: Any = Column(Text, nullable=True)
    readiness_json: Any = Column(CanonicalJSON(), nullable=True)
    approval_status: Any = Column(String(32), nullable=False, default="PENDING")
    approved_by_id: Any = Column(PortableUUID(), nullable=True)
    approved_at: Any = Column(PortableUTC(), nullable=True)
    approval_rationale: Any = Column(Text, nullable=True)
    superseded_by_id: Any = Column(PortableUUID(), nullable=True)
    requested_by_id: Any = Column(PortableUUID(), nullable=False)
    requested_at: Any = Column(PortableUTC(), nullable=False)
    completed_at: Any = Column(PortableUTC(), nullable=True)
    created_at: Any = Column(PortableUTC(), nullable=False)
    input_id: Any = Column(PortableUUID(), nullable=True)
    mode: Any = Column(String(32), nullable=True)
    capability: Any = Column(String(32), nullable=True)
    authority: Any = Column(String(32), nullable=False, default="LEGACY_UNPINNED")
    phase: Any = Column(String(32), nullable=False, default="PENDING")
    row_version: Any = Column(Integer, nullable=False, default=1)
    semantic_input_hash: Any = Column(Sha256Hex(), nullable=True)
    attempt_number: Any = Column(Integer, nullable=False, default=0)
    lease_token: Any = Column(String(128), nullable=True)
    lease_expires_at: Any = Column(PortableUTC(), nullable=True)
    manifest_hash: Any = Column(Sha256Hex(), nullable=True)
    rerun_reason: Any = Column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["application_id"], ["applications.id"], name="fk_gnrn_app"),
        ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_gnrn_int"),
        ForeignKeyConstraint(["snapshot_id"], ["int_snaps.id"], name="fk_gnrn_snp"),
        ForeignKeyConstraint(["base_artifact_id"], ["topo_base.id"], name="fk_gnrn_bas"),
        ForeignKeyConstraint(["requested_by_id"], ["actors.id"], name="fk_gnrn_req"),
        ForeignKeyConstraint(["approved_by_id"], ["actors.id"], name="fk_gnrn_apr"),
        ForeignKeyConstraint(["superseded_by_id"], ["gen_runs.id"], name="fk_gnrn_sup"),
        UniqueConstraint(
            "intake_id",
            "semantic_input_hash",
            "attempt_number",
            name="uq_grun_attempt",
        ),
        Index("ix_gnrn_intake", "intake_id"),
        Index("ix_gnrn_status", "status"),
        Index("ix_gnrn_input", "input_id"),
    )


class GeneratedArtifact(Base):
    __tablename__ = "gen_artifacts"

    id: Any = Column(PortableUUID(), primary_key=True)
    generation_run_id: Any = Column(PortableUUID(), nullable=False)
    artifact_type: Any = Column(String(32), nullable=False)
    filename: Any = Column(String(255), nullable=False)
    mime_type: Any = Column(String(100), nullable=False)
    size_bytes: Any = Column(Integer, nullable=False)
    sha256_hex: Any = Column(Sha256Hex(), nullable=False)
    content_address: Any = Column(String(255), nullable=False)
    created_at: Any = Column(PortableUTC(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["generation_run_id"], ["gen_runs.id"], name="fk_gnaf_run"),
        UniqueConstraint("generation_run_id", "artifact_type", name="uq_gart_type"),
        Index("ix_gnaf_run", "generation_run_id"),
        Index("ix_gnaf_type", "artifact_type"),
    )


class TopologyCompatibility(Base):
    __tablename__ = "topo_compat"

    id: Any = Column(PortableUUID(), primary_key=True)
    base_artifact_id: Any = Column(PortableUUID(), nullable=False)
    base_sha256: Any = Column(Sha256Hex(), nullable=False)
    profile_id: Any = Column(String(128), nullable=False)
    profile_version: Any = Column(String(32), nullable=False)
    profile_hash: Any = Column(Sha256Hex(), nullable=False)
    selection_json: Any = Column(CanonicalJSON(), nullable=False)
    selection_hash: Any = Column(Sha256Hex(), nullable=False)
    capability: Any = Column(String(32), nullable=False)
    parser_policy_hash: Any = Column(Sha256Hex(), nullable=False)
    compatibility_key: Any = Column(Sha256Hex(), nullable=False)
    result_json: Any = Column(CanonicalJSON(), nullable=False)
    result_hash: Any = Column(Sha256Hex(), nullable=False)
    checked_by_id: Any = Column(PortableUUID(), nullable=False)
    checked_at: Any = Column(PortableUTC(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["base_artifact_id"], ["topo_base.id"], name="fk_tcmp_base"),
        ForeignKeyConstraint(["checked_by_id"], ["actors.id"], name="fk_tcmp_actor"),
        UniqueConstraint("compatibility_key", name="uq_tcmp_key"),
        Index("ix_tcmp_base", "base_artifact_id"),
    )


class TopologyCapture(Base):
    __tablename__ = "topo_captures"

    id: Any = Column(PortableUUID(), primary_key=True)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    content_epoch: Any = Column(Integer, nullable=False)
    schema_version: Any = Column(String(32), nullable=False)
    canonical_json: Any = Column(CanonicalJSON(), nullable=False)
    sha256_hex: Any = Column(Sha256Hex(), nullable=False)
    captured_by_id: Any = Column(PortableUUID(), nullable=False)
    captured_at: Any = Column(PortableUTC(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_tcap_intake"),
        ForeignKeyConstraint(["captured_by_id"], ["actors.id"], name="fk_tcap_actor"),
        Index("ix_tcap_intake", "intake_id"),
    )


class TopologyInput(Base):
    __tablename__ = "topo_inputs"

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    mode: Any = Column(String(32), nullable=False)
    snapshot_id: Any = Column(PortableUUID(), nullable=True)
    capture_id: Any = Column(PortableUUID(), nullable=True)
    projection_json: Any = Column(CanonicalJSON(), nullable=False)
    projection_sha256: Any = Column(Sha256Hex(), nullable=False)
    selection_json: Any = Column(CanonicalJSON(), nullable=False)
    selection_sha256: Any = Column(Sha256Hex(), nullable=False)
    capability: Any = Column(String(32), nullable=False)
    base_artifact_id: Any = Column(PortableUUID(), nullable=False)
    base_sha256: Any = Column(Sha256Hex(), nullable=False)
    profile_id: Any = Column(String(128), nullable=False)
    profile_hash: Any = Column(Sha256Hex(), nullable=False)
    catalog_sha256: Any = Column(Sha256Hex(), nullable=False)
    generator_version: Any = Column(String(64), nullable=False)
    parser_policy_hash: Any = Column(Sha256Hex(), nullable=False)
    layout_policy_hash: Any = Column(Sha256Hex(), nullable=False)
    result_policy_hash: Any = Column(Sha256Hex(), nullable=False)
    semantic_input_hash: Any = Column(Sha256Hex(), nullable=False)
    captured_by_id: Any = Column(PortableUUID(), nullable=False)
    captured_at: Any = Column(PortableUTC(), nullable=False)
    compatibility_id: Any = Column(PortableUUID(), nullable=True)
    compatibility_key: Any = Column(Sha256Hex(), nullable=True)
    compatibility_result_hash: Any = Column(Sha256Hex(), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["application_id"], ["applications.id"], name="fk_tinp_app"),
        ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_tinp_intake"),
        ForeignKeyConstraint(["base_artifact_id"], ["topo_base.id"], name="fk_tinp_base"),
        ForeignKeyConstraint(["snapshot_id"], ["int_snaps.id"], name="fk_tinp_snap"),
        ForeignKeyConstraint(["capture_id"], ["topo_captures.id"], name="fk_tinp_cap"),
        ForeignKeyConstraint(["captured_by_id"], ["actors.id"], name="fk_tinp_actor"),
        ForeignKeyConstraint(["compatibility_id"], ["topo_compat.id"], name="fk_tinp_cmp"),
        UniqueConstraint("intake_id", "semantic_input_hash", name="uq_tinp_semantic"),
        Index("ix_tinp_intake", "intake_id"),
    )


class GenerationReservation(Base):
    __tablename__ = "gen_keys"

    id: Any = Column(PortableUUID(), primary_key=True)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    semantic_input_hash: Any = Column(Sha256Hex(), nullable=False)
    run_id: Any = Column(PortableUUID(), nullable=False)
    reservation_version: Any = Column(Integer, nullable=False, default=1)
    created_at: Any = Column(PortableUTC(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_gkey_intake"),
        ForeignKeyConstraint(["run_id"], ["gen_runs.id"], name="fk_gkey_run"),
        UniqueConstraint("intake_id", "semantic_input_hash", name="uq_gkey_semantic"),
        Index("ix_gkey_run", "run_id"),
    )


class TopologyReview(Base):
    __tablename__ = "topo_reviews"

    id: Any = Column(PortableUUID(), primary_key=True)
    entity_type: Any = Column(String(32), nullable=False)
    entity_id: Any = Column(PortableUUID(), nullable=False)
    run_id: Any = Column(PortableUUID(), nullable=True)
    base_artifact_id: Any = Column(PortableUUID(), nullable=True)
    decision: Any = Column(String(32), nullable=False)
    compatibility_result_hash: Any = Column(Sha256Hex(), nullable=True)
    manifest_hash: Any = Column(Sha256Hex(), nullable=True)
    rationale: Any = Column(Text, nullable=False)
    issue_decisions: Any = Column(CanonicalJSON(), nullable=True)
    actor_id: Any = Column(PortableUUID(), nullable=False)
    self_review: Any = Column(Integer, nullable=False, default=0)
    reviewed_at: Any = Column(PortableUTC(), nullable=False)

    __table_args__ = (Index("ix_trev_entity", "entity_type", "entity_id"),)
