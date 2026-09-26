"""
AI mapping run persistence models (PAI-5).

Stores append-only lineage for provider-backed mapping attempts without
persisting prompts, responses, credentials, or endpoint URLs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, ForeignKeyConstraint, Index, Integer, String

from migration_intake.persistence.models import (
    Base,
    CanonicalJSON,
    PortableUTC,
    PortableUUID,
    Sha256Hex,
)


class AIMappingRun(Base):
    """
    Append-only lineage record for one candidate mapping run.

    Table: ``ai_mapping_runs``
    """

    __tablename__ = "ai_mapping_runs"
    __table_args__ = (
        ForeignKeyConstraint(["application_id"], ["applications.id"], name="fk_airun_app"),
        ForeignKeyConstraint(["intake_id"], ["intakes.id"], name="fk_airun_int"),
        ForeignKeyConstraint(["evidence_item_id"], ["evidence_items.id"], name="fk_airun_evi"),
        ForeignKeyConstraint(["created_by_id"], ["actors.id"], name="fk_airun_act"),
        Index("ix_airun_app", "application_id"),
        Index("ix_airun_int", "intake_id"),
        Index("ix_airun_evi", "evidence_item_id"),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    evidence_item_id: Any = Column(PortableUUID(), nullable=False)

    provider_id: Any = Column(String(64), nullable=False)
    profile_id: Any = Column(String(128), nullable=False)
    model_id: Any = Column(String(128), nullable=False)
    prompt_template_version: Any = Column(String(32), nullable=False)
    classification: Any = Column(String(32), nullable=False)

    fragment_count: Any = Column(Integer(), nullable=False, default=0)
    request_hash: Any = Column(Sha256Hex(), nullable=True)
    response_hash: Any = Column(Sha256Hex(), nullable=True)
    attempt_count: Any = Column(Integer(), nullable=False, default=1)

    status: Any = Column(String(32), nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    failure_category: Any = Column(String(64), nullable=True)
    failure_detail_redacted: Any = Column(String(255), nullable=True)
    metrics_json: Any = Column(CanonicalJSON(), nullable=True)

    candidate_count: Any = Column(Integer(), nullable=False, default=0)
    finding_count: Any = Column(Integer(), nullable=False, default=0)

    started_at: Any = Column(PortableUTC(), nullable=False)
    finished_at: Any = Column(PortableUTC(), nullable=True)
    created_by_id: Any = Column(PortableUUID(), nullable=False)
    created_at: Any = Column(PortableUTC(), nullable=False)
