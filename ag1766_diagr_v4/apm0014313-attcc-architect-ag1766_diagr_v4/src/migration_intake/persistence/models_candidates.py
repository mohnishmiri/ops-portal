"""
Candidate persistence models (P06).

Candidates are proposed values from imports or AI that require review
before becoming canonical answers. This module defines the SQLAlchemy
models for persisting candidates and their provenance.

All models use the shared Base from models.py to ensure a single
metadata instance for migrations.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from migration_intake.persistence.models import Base, CanonicalJSON, PortableUUID

# ─────────────────────────────────────────────────────────────────────────────
# candidates
# ─────────────────────────────────────────────────────────────────────────────


class Candidate(Base):
    """
    A proposed value from import or AI requiring review.

    Candidates are immutable records of proposals. The original proposal
    is preserved even after acceptance-with-edit. Candidates link to
    their source evidence and target question.

    Table: ``candidates``
    PK auto-name:  ``pk_candidates``              (13 chars ✓)
    FK explicit:   ``fk_cand_run``, ``fk_cand_app``, ``fk_cand_intake``,
                   ``fk_cand_evidence``, ``fk_cand_decided_by``
    """

    __tablename__ = "candidates"
    __table_args__ = (
        # FK: candidates.import_run_id → import_runs.id
        ForeignKeyConstraint(
            ["import_run_id"],
            ["import_runs.id"],
            name="fk_cand_run",
        ),
        # FK: candidates.application_id → applications.id
        ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_cand_app",
        ),
        # FK: candidates.intake_id → intakes.id
        ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_cand_intake",
        ),
        # FK: candidates.evidence_item_id → evidence_items.id
        ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name="fk_cand_evidence",
        ),
        # FK: candidates.decided_by_id → actors.id
        ForeignKeyConstraint(
            ["decided_by_id"],
            ["actors.id"],
            name="fk_cand_decided_by",
        ),
        # Index for intake + state queries (most common access pattern)
        Index("ix_cand_intake_state", "intake_id", "state"),
        # Index for import run queries
        Index("ix_cand_run", "import_run_id"),
        # Index for target queries (question code lookups)
        Index("ix_cand_target", "intake_id", "target_kind", "target_key"),
        # Index for evidence queries
        Index("ix_cand_evidence", "evidence_item_id"),
    )

    # Primary key
    id: Any = Column(PortableUUID(), primary_key=True)

    # Source references
    import_run_id: Any = Column(PortableUUID(), nullable=False)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    evidence_item_id: Any = Column(PortableUUID(), nullable=False)

    # Target identification
    target_kind: Any = Column(String(32), nullable=False)  # QUESTION, REGISTER, etc.
    target_key: Any = Column(String(128), nullable=False)  # question_code, register_code
    origin: Any = Column(String(64), nullable=False)  # adapter name, AI model, etc.

    # Version tracking for reproducibility
    extractor_version: Any = Column(String(32), nullable=False)
    contract_version: Any = Column(String(32), nullable=False)
    response_schema_version: Any = Column(String(32), nullable=True)

    # Source location within evidence
    source_locator: Any = Column(CanonicalJSON(), nullable=True)  # sheet, row, cell, etc.

    # Values
    raw_value_json: Any = Column(CanonicalJSON(), nullable=False)  # original extracted value
    normalized_value_json: Any = Column(CanonicalJSON(), nullable=True)  # normalized for schema
    scope_json: Any = Column(CanonicalJSON(), nullable=True)  # environment, site, etc.

    # Quality indicators
    confidence: Any = Column(Float(), nullable=True)  # 0.0-1.0
    reconciliation_outcome: Any = Column(String(32), nullable=True)  # UNIQUE, CONFLICT, etc.
    validation_json: Any = Column(CanonicalJSON(), nullable=True)  # validation results

    # Stale-answer detection (for legacy intake imports)
    base_answer_revision: Any = Column(Integer(), nullable=True)  # answer revision at import time

    # State
    state: Any = Column(String(32), nullable=False, default="PROPOSED")

    # Concurrency control
    row_version: Any = Column(Integer(), nullable=False, default=1)
    created_at: Any = Column(DateTime(timezone=True), nullable=False)

    # Decision fields (populated when state changes from PROPOSED)
    decided_by_id: Any = Column(PortableUUID(), nullable=True)
    decided_at: Any = Column(DateTime(timezone=True), nullable=True)
    decision_rationale: Any = Column(Text(), nullable=True)
    accepted_value_json: Any = Column(CanonicalJSON(), nullable=True)  # value after edit


# ─────────────────────────────────────────────────────────────────────────────
# candidate_findings
# ─────────────────────────────────────────────────────────────────────────────


class CandidateFinding(Base):
    """
    A finding or issue discovered during candidate extraction.

    Findings are informational records about extraction quality,
    validation issues, or conflicts that don't prevent candidate
    creation but should be reviewed.

    Table: ``candidate_findings``
    PK auto-name:  ``pk_candidate_findings``      (21 chars ✓)
    FK explicit:   ``fk_cfind_cand``, ``fk_cfind_run``
    """

    __tablename__ = "candidate_findings"
    __table_args__ = (
        # FK: candidate_findings.candidate_id → candidates.id
        ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name="fk_cfind_cand",
        ),
        # FK: candidate_findings.import_run_id → import_runs.id
        ForeignKeyConstraint(
            ["import_run_id"],
            ["import_runs.id"],
            name="fk_cfind_run",
        ),
        # Index for candidate queries
        Index("ix_cfind_cand", "candidate_id"),
        # Index for run queries
        Index("ix_cfind_run", "import_run_id"),
    )

    # Primary key
    id: Any = Column(PortableUUID(), primary_key=True)

    # References (candidate_id is nullable for run-level findings)
    candidate_id: Any = Column(PortableUUID(), nullable=True)
    import_run_id: Any = Column(PortableUUID(), nullable=False)

    # Finding details
    finding_type: Any = Column(String(64), nullable=False)  # VALIDATION_WARNING, CONFLICT, etc.
    severity: Any = Column(String(16), nullable=False)  # INFO, WARNING, ERROR
    message: Any = Column(Text(), nullable=False)
    details_json: Any = Column(CanonicalJSON(), nullable=True)

    # Location
    source_locator: Any = Column(CanonicalJSON(), nullable=True)

    # Timestamps
    created_at: Any = Column(DateTime(timezone=True), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# answer_evidence_links
# ─────────────────────────────────────────────────────────────────────────────


class AnswerEvidenceLink(Base):
    """
    Links an answer revision to its source evidence.

    This provides traceability from canonical answers back to the
    evidence that supported them, whether from import acceptance
    or manual citation.

    Table: ``answer_evidence_links``
    PK auto-name:  ``pk_answer_evidence_links``   (24 chars ✓)
    UQ auto-name:  ``uq_answer_evidence_links_revision_id`` (37 chars ✓)
    FK explicit:   ``fk_ael_rev``, ``fk_ael_evidence``, ``fk_ael_cand``
    """

    __tablename__ = "answer_evidence_links"
    __table_args__ = (
        # Unique constraint: one link per revision + evidence pair
        # UQ auto-name would be 36 chars, so we use explicit name
        UniqueConstraint("revision_id", "evidence_item_id", name="uq_ael_rev_evid"),
        # FK: answer_evidence_links.revision_id → ans_revisions.id
        ForeignKeyConstraint(
            ["revision_id"],
            ["ans_revisions.id"],
            name="fk_ael_rev",
        ),
        # FK: answer_evidence_links.evidence_item_id → evidence_items.id
        ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name="fk_ael_evidence",
        ),
        # FK: answer_evidence_links.candidate_id → candidates.id (nullable)
        ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name="fk_ael_cand",
        ),
        # Index for revision queries
        Index("ix_ael_rev", "revision_id"),
        # Index for evidence queries
        Index("ix_ael_evidence", "evidence_item_id"),
    )

    # Primary key
    id: Any = Column(PortableUUID(), primary_key=True)

    # References
    revision_id: Any = Column(PortableUUID(), nullable=False)
    evidence_item_id: Any = Column(PortableUUID(), nullable=False)
    candidate_id: Any = Column(PortableUUID(), nullable=True)  # if from import acceptance

    # Link metadata
    link_type: Any = Column(String(32), nullable=False)  # IMPORT_ACCEPTANCE, MANUAL_CITATION
    source_locator: Any = Column(CanonicalJSON(), nullable=True)

    # Timestamps
    created_at: Any = Column(DateTime(timezone=True), nullable=False)
