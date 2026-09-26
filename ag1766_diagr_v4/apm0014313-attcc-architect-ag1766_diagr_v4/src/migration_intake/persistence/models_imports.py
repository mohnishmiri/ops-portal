"""
ORM model classes — P05b (Import Runs, Sheet Results, Findings Persistence).

Three new tables supplementing the core tables in models.py and models_evidence.py:
  import_runs          — one row per import execution attempt
  import_sheet_results — one row per worksheet processed in a run
  import_findings      — structured finding records emitted during a run

Design rules (identical to models.py and models_evidence.py):
- Do NOT edit models.py or models_evidence.py; extend via this separate module.
- All constraint names ≤ 30 characters (Oracle 12c conservative limit).
- All column names ≤ 30 characters.
- UUIDs as PortableUUID, timestamps as PortableUTC, JSON as CanonicalJSON —
  identical type conventions to models.py.
- Python-side defaults (default=) match the existing models.py convention.
- State codes: plain String — NOT database-native enum types.

Constraint names
----------------
import_runs FKs:
  fk_irun_appl  (12) — application_id → applications.id
  fk_irun_intk  (12) — intake_id → intakes.id
  fk_irun_evid  (12) — evidence_item_id → evidence_items.id
  fk_irun_act   (11) — created_by_id → actors.id

import_sheet_results FKs:
  fk_isht_irun  (12) — run_id → import_runs.id

import_findings FKs:
  fk_ifnd_irun  (12) — run_id → import_runs.id
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Integer,
    String,
)

from migration_intake.persistence.naming import Base
from migration_intake.persistence.types import (
    CanonicalJSON,
    PortableUTC,
    PortableUUID,
)

__all__ = [
    "ImportFinding",
    "ImportRun",
    "ImportSheetResult",
]


# ─────────────────────────────────────────────────────────────────────────────
# import_runs
# ─────────────────────────────────────────────────────────────────────────────


class ImportRun(Base):
    """
    One execution attempt of an import parser against an evidence file.

    Table: ``import_runs``
    PK auto-name:  ``pk_import_runs``  (14 chars ✓)
    FK explicit:   ``fk_irun_appl``    (12 chars ✓)
    FK explicit:   ``fk_irun_intk``    (12 chars ✓)
    FK explicit:   ``fk_irun_evid``    (12 chars ✓)
    FK explicit:   ``fk_irun_act``     (11 chars ✓)
    """

    __tablename__ = "import_runs"
    __table_args__ = (
        # FK: import_runs.application_id → applications.id
        # auto-name: fk_import_runs_application_id_applications = 42 chars ✗
        ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_irun_appl",
        ),
        # FK: import_runs.intake_id → intakes.id
        # auto-name: fk_import_runs_intake_id_intakes = 32 chars ✗
        ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_irun_intk",
        ),
        # FK: import_runs.evidence_item_id → evidence_items.id
        # auto-name: fk_import_runs_evidence_item_id_evidence_items = 46 chars ✗
        ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name="fk_irun_evid",
        ),
        # FK: import_runs.created_by_id → actors.id
        # auto-name: fk_import_runs_created_by_id_actors = 35 chars ✗
        ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_irun_act",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    intake_id: Any = Column(PortableUUID(), nullable=True)
    evidence_item_id: Any = Column(PortableUUID(), nullable=True)
    import_lane: Any = Column(String(30), nullable=True)
    contract_name: Any = Column(String(100), nullable=False)
    parser_version: Any = Column(String(50), nullable=False)
    state: Any = Column(String(30), nullable=False, default="PENDING")
    total_sheets: Any = Column(Integer(), nullable=True)
    total_candidates: Any = Column(Integer(), nullable=False, default=0)
    total_findings: Any = Column(Integer(), nullable=False, default=0)
    identity_decision: Any = Column(String(40), nullable=True)
    source_identity_raw: Any = Column(String(500), nullable=True)
    source_identity_normalized: Any = Column(String(500), nullable=True)
    matched_identifier_type: Any = Column(String(20), nullable=True)
    identity_detail: Any = Column(CanonicalJSON(), nullable=True)
    started_at: Any = Column(PortableUTC(), nullable=True)
    completed_at: Any = Column(PortableUTC(), nullable=True)
    created_at: Any = Column(PortableUTC(), nullable=False)
    created_by_id: Any = Column(PortableUUID(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# import_sheet_results
# ─────────────────────────────────────────────────────────────────────────────


class ImportSheetResult(Base):
    """
    One worksheet result within an import run.

    Table: ``import_sheet_results``
    PK auto-name:  ``pk_import_sheet_results``  (23 chars ✓)
    FK explicit:   ``fk_isht_irun``             (12 chars ✓)
    """

    __tablename__ = "import_sheet_results"
    __table_args__ = (
        # FK: import_sheet_results.run_id → import_runs.id
        # auto-name: fk_import_sheet_results_run_id_import_runs = 42 chars ✗
        ForeignKeyConstraint(
            ["run_id"],
            ["import_runs.id"],
            name="fk_isht_irun",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    run_id: Any = Column(PortableUUID(), nullable=False)
    sheet_name: Any = Column(String(200), nullable=False)
    outcome: Any = Column(String(30), nullable=False)
    candidate_count: Any = Column(Integer(), nullable=False, default=0)
    finding_count: Any = Column(Integer(), nullable=False, default=0)
    blank_rows_skipped: Any = Column(Integer(), nullable=False, default=0)
    error_message: Any = Column(String(1000), nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# import_findings
# ─────────────────────────────────────────────────────────────────────────────


class ImportFinding(Base):
    """
    A structured finding emitted during an import run.

    Table: ``import_findings``
    PK auto-name:  ``pk_import_findings``  (18 chars ✓)
    FK explicit:   ``fk_ifnd_irun``        (12 chars ✓)
    """

    __tablename__ = "import_findings"
    __table_args__ = (
        # FK: import_findings.run_id → import_runs.id
        # auto-name: fk_import_findings_run_id_import_runs = 37 chars ✗
        ForeignKeyConstraint(
            ["run_id"],
            ["import_runs.id"],
            name="fk_ifnd_irun",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    run_id: Any = Column(PortableUUID(), nullable=False)
    sheet_name: Any = Column(String(200), nullable=False)
    finding_type: Any = Column(String(100), nullable=False)
    severity: Any = Column(String(20), nullable=False, default="WARNING")
    source_locator: Any = Column(String(500), nullable=True)
    detail: Any = Column(CanonicalJSON(), nullable=True)
