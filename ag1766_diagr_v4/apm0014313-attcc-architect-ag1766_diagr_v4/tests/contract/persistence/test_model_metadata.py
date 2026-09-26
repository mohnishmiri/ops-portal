"""
Contract tests for ORM model metadata — P02 (Initial ORM model tranche).

TDD discipline: tests are written first and must fail with ImportError /
AttributeError before naming.py and models.py exist.  After implementation
every test must pass.

Coverage:
  1.  All 12 domain tables exist in Base.metadata.
  2.  Every PK constraint name matches pk_<table>.
  3.  Every FK constraint has an explicit (non-None) name.
  4.  Every constraint / index name is ≤ 30 chars (Oracle 12c safe).
  5.  Constraint names are stable — two collections return identical results.
  6.  Base.metadata.create_all() on in-memory SQLite raises no error.
  7.  create_all + drop_all complete without FK cycle errors.
  8.  ans_instances/ans_revisions cycle insert pattern (NULL → insert → update).
  9.  UNIQUE(intake_id, question_id) exists on ans_instances.
 10.  UNIQUE(identifier_type, normalized_value) exists on app_identifiers.
 11.  source_sha256 column on cat_releases has a unique constraint.
 12.  audit_events has indexes on (entity_type, entity_id) and occurred_at.
 13.  Actor + Application round-trip (insert one session, reload in another).
 14.  CatalogRelease + CatalogSection + CatalogQuestion round-trip.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Session

import migration_intake.persistence.models
import migration_intake.persistence.models_candidates
import migration_intake.persistence.models_evidence
import migration_intake.persistence.models_imports
import migration_intake.persistence.models_interfaces
import migration_intake.persistence.models_resources
import migration_intake.persistence.models_topology  # noqa: F401
from migration_intake.persistence.database import create_engine_from_url
from migration_intake.persistence.models import (
    Actor,
    AnswerInstance,
    AnswerRevision,
    Application,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)

# ── RED imports — fail with ImportError before implementation ──────────────
from migration_intake.persistence.naming import Base

# ── Constants ──────────────────────────────────────────────────────────────

EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        # P02 — 12 core tables
        "actors",
        "applications",
        "app_identifiers",
        "cat_releases",
        "cat_sections",
        "cat_questions",
        "cat_options",
        "cat_src_rels",
        "intakes",
        "ans_instances",
        "ans_revisions",
        "audit_events",
        # P05 — 3 evidence / wave-util tables
        "evidence_items",
        "wave_util_rows",
        "wave_util_revisions",
        # P05b — 3 import run / sheet result / finding tables
        "import_runs",
        "import_sheet_results",
        "import_findings",
        # P06 — 3 candidate / finding / evidence link tables
        "candidates",
        "candidate_findings",
        "answer_evidence_links",
        # P07 — 1 snapshot table
        "int_snaps",
        # Interface register — single canonical table (no revision history)
        "interfaces",
        # Topology generation — base snapshot, run, and artifact tables
        "topo_base",
        "topo_compat",
        "topo_captures",
        "topo_inputs",
        "topo_reviews",
        "gen_runs",
        "gen_artifacts",
        "gen_keys",
        # AI mapping lineage
        "ai_mapping_runs",
        # Resource lifecycle and relationship history
        "res_resources",
        "res_revisions",
        "res_links",
        "res_link_revisions",
    }
)

MAX_CONSTRAINT_NAME_LEN: int = 30


# ── Helpers ────────────────────────────────────────────────────────────────


def _sha(char: str) -> str:
    """Return a valid 64-char lowercase hex string filled with `char`."""
    assert char in "0123456789abcdef", f"not a hex char: {char!r}"
    return char * 64


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _collect_names(metadata) -> list[str]:
    """Collect every non-None constraint and index name from *metadata*."""
    names: list[str] = []
    for table in metadata.tables.values():
        for constraint in table.constraints:
            if constraint.name:
                names.append(constraint.name)
        for index in table.indexes:
            if index.name:
                names.append(index.name)
    return names


# ── Shared engine fixture (module-scoped to keep tests fast) ───────────────


@pytest.fixture(scope="module")
def mem_engine():
    """In-memory SQLite engine with all tables created once per module."""
    engine = create_engine_from_url(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    # In-memory DB is destroyed when engine is disposed; drop_all not needed.
    engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# Test 1 — All tables exist in metadata
# ═══════════════════════════════════════════════════════════════════════════


def test_all_expected_tables_present() -> None:
    """All domain tables are registered in Base.metadata after import."""
    actual = frozenset(Base.metadata.tables.keys())
    assert actual == EXPECTED_TABLES, (
        f"Missing tables: {EXPECTED_TABLES - actual}\n"
        f"Extra tables:   {actual - EXPECTED_TABLES}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 2 — PK names follow pk_<table> convention
# ═══════════════════════════════════════════════════════════════════════════


def test_pk_constraint_names_follow_convention() -> None:
    """Every PK constraint name is exactly pk_<table_name>."""
    for table_name, table in Base.metadata.tables.items():
        pk = table.primary_key
        assert pk.name is not None, (
            f"PK on {table_name!r} has name=None"
        )
        expected = f"pk_{table_name}"
        assert pk.name == expected, (
            f"PK on {table_name!r}: expected {expected!r}, got {pk.name!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Test 3 — Every FK constraint has an explicit name
# ═══════════════════════════════════════════════════════════════════════════


def test_every_fk_constraint_has_name() -> None:
    """Every ForeignKeyConstraint carries a non-None, non-empty name."""
    violations: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint) and not constraint.name:
                cols = [e.parent.name for e in constraint.elements]
                violations.append(f"{table_name}.fk({cols}) has no name")
    assert not violations, "\n".join(violations)


# ═══════════════════════════════════════════════════════════════════════════
# Test 4 — Every constraint/index name is ≤ 30 chars
# ═══════════════════════════════════════════════════════════════════════════


def test_all_constraint_names_oracle_safe() -> None:
    """Every constraint and index name is ≤ 30 characters (Oracle 12c limit)."""
    violations: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        for constraint in table.constraints:
            name = constraint.name
            if name and len(name) > MAX_CONSTRAINT_NAME_LEN:
                violations.append(
                    f"{table_name}.constraint({name!r}) = {len(name)} chars"
                )
        for index in table.indexes:
            name = index.name
            if name and len(name) > MAX_CONSTRAINT_NAME_LEN:
                violations.append(
                    f"{table_name}.index({name!r}) = {len(name)} chars"
                )
    assert not violations, (
        "Constraint/index names exceed Oracle 12c 30-char limit:\n"
        + "\n".join(violations)
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 5 — Constraint names are stable across two collections
# ═══════════════════════════════════════════════════════════════════════════


def test_constraint_names_are_stable() -> None:
    """Collecting constraint names twice from the same metadata is identical."""
    first = sorted(_collect_names(Base.metadata))
    second = sorted(_collect_names(Base.metadata))
    assert first == second, "Constraint names differ between two collections"


# ═══════════════════════════════════════════════════════════════════════════
# Test 6 — create_all on SQLite succeeds
# ═══════════════════════════════════════════════════════════════════════════


def test_create_all_on_sqlite_succeeds() -> None:
    """Base.metadata.create_all() on an in-memory SQLite engine raises no error."""
    engine = create_engine_from_url(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.create_all(engine)  # must not raise
    finally:
        engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# Test 7 — create_all + drop_all without FK cycle error
# ═══════════════════════════════════════════════════════════════════════════


def test_create_and_drop_all_no_cycle_error() -> None:
    """All tables are created and dropped without FK cycle or ordering errors."""
    engine = create_engine_from_url(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.create_all(engine)
        Base.metadata.drop_all(engine)
    finally:
        engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# Test 8 — ans_instances/ans_revisions cycle insert pattern
# ═══════════════════════════════════════════════════════════════════════════


def test_ans_instances_revisions_cycle_insert_pattern(mem_engine) -> None:
    """
    The circular FK (ans_instances.current_rev_id → ans_revisions.id) is
    broken at the application layer:
      1. Insert ans_instances with current_rev_id=NULL.
      2. Insert ans_revisions (instance_id → existing ans_instances row).
      3. UPDATE ans_instances.current_rev_id = new revision id.
    No FK violation must occur at any step.
    """
    now = _now()
    actor_id = uuid.uuid4()
    app_id = uuid.uuid4()
    cat_id = uuid.uuid4()
    sec_id = uuid.uuid4()
    q_id = uuid.uuid4()
    intake_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    rev_id = uuid.uuid4()

    with Session(mem_engine) as session:
        # ── Level 0: no FK dependencies ──────────────────────────────────────
        session.add(Actor(id=actor_id, display_name="Cycle Actor", created_at=now))
        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="0.1.0",
                source_filename="cycle.yaml",
                source_sha256=_sha("c"),
                compiler_version="0.1",
                pub_state="PUBLISHED",
                created_at=now,
            )
        )
        # Flush parents before dependents (no relationship() on models, so the
        # ORM unit-of-work does not auto-sort by FK; we flush level-by-level).
        session.flush()

        # ── Level 1: depend on Actor and/or CatalogRelease ───────────────────
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Cycle App",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.add(
            CatalogSection(
                id=sec_id,
                release_id=cat_id,
                section_code="CYC",
                display_name="Cycle Section",
                display_order=1,
            )
        )
        session.flush()

        # ── Level 2: depend on CatalogSection ────────────────────────────────
        session.add(
            CatalogQuestion(
                id=q_id,
                section_id=sec_id,
                question_code="CYC-001",
                question_text="Cycle test question?",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="MANUAL",
                display_order=1,
                is_active=True,
            )
        )
        session.flush()

        # ── Level 3: depend on Application, CatalogRelease, Actor ────────────
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=cat_id,
                state="DRAFT",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.flush()

        # ── Step 1 — insert ans_instances with current_rev_id=NULL ───────────
        # (depends on Intake and CatalogQuestion)
        session.add(
            AnswerInstance(
                id=inst_id,
                intake_id=intake_id,
                question_id=q_id,
                created_at=now,
                current_rev_id=None,
                applicability="APPLICABLE",
                value_state="EMPTY",
                review_state="UNREVIEWED",
                updated_at=now,
                row_version=1,
            )
        )
        session.flush()

        # ── Step 2 — insert ans_revisions referencing the instance ────────────
        session.add(
            AnswerRevision(
                id=rev_id,
                instance_id=inst_id,
                revision_number=1,
                response_json={"value": "cycle-test"},
                confirm_state="DRAFT",
                authored_at=now,
                authored_by_id=actor_id,
            )
        )
        session.flush()

        # ── Step 3 — update current_rev_id (breaks the insertion cycle) ───────
        inst = session.get(AnswerInstance, inst_id)
        assert inst is not None
        inst.current_rev_id = rev_id
        session.commit()

    # Verify the final state in a fresh session
    with Session(mem_engine) as session:
        inst = session.get(AnswerInstance, inst_id)
        assert inst is not None, "AnswerInstance not found after commit"
        assert inst.current_rev_id == rev_id, (
            f"current_rev_id mismatch: {inst.current_rev_id} != {rev_id}"
        )
        rev = session.get(AnswerRevision, rev_id)
        assert rev is not None, "AnswerRevision not found after commit"
        assert rev.instance_id == inst_id


# ═══════════════════════════════════════════════════════════════════════════
# Test 9 — UNIQUE(intake_id, question_id) on ans_instances
# ═══════════════════════════════════════════════════════════════════════════


def test_ans_instances_unique_intake_question() -> None:
    """ans_instances has a UNIQUE constraint covering (intake_id, question_id)."""
    table = Base.metadata.tables["ans_instances"]
    col_sets = [
        frozenset(col.name for col in c.columns)
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = frozenset({"intake_id", "question_id"})
    assert target in col_sets, (
        f"UNIQUE(intake_id, question_id) missing from ans_instances; found: {col_sets}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 10 — UNIQUE(identifier_type, normalized_value) on app_identifiers
# ═══════════════════════════════════════════════════════════════════════════


def test_app_identifiers_unique_type_value() -> None:
    """app_identifiers has UNIQUE(identifier_type, normalized_value)."""
    table = Base.metadata.tables["app_identifiers"]
    col_sets = [
        frozenset(col.name for col in c.columns)
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = frozenset({"identifier_type", "normalized_value"})
    assert target in col_sets, (
        f"UNIQUE(identifier_type, normalized_value) missing from app_identifiers; found: {col_sets}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 11 — source_sha256 UNIQUE on cat_releases
# ═══════════════════════════════════════════════════════════════════════════


def test_cat_releases_source_sha256_unique() -> None:
    """cat_releases.source_sha256 is covered by a unique constraint."""
    table = Base.metadata.tables["cat_releases"]
    col_sets = [
        frozenset(col.name for col in c.columns)
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    ]
    target = frozenset({"source_sha256"})
    assert target in col_sets, (
        f"UNIQUE(source_sha256) missing from cat_releases; found: {col_sets}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 12 — audit_events indexes
# ═══════════════════════════════════════════════════════════════════════════


def test_audit_events_has_required_indexes() -> None:
    """audit_events carries indexes on (entity_type, entity_id) and occurred_at."""
    table = Base.metadata.tables["audit_events"]
    index_col_sets = [
        frozenset(col.name for col in idx.columns)
        for idx in table.indexes
    ]
    assert frozenset({"entity_type", "entity_id"}) in index_col_sets, (
        f"Missing index on (entity_type, entity_id); found: {index_col_sets}"
    )
    assert frozenset({"occurred_at"}) in index_col_sets, (
        f"Missing index on occurred_at; found: {index_col_sets}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 13 — Actor + Application round-trip
# ═══════════════════════════════════════════════════════════════════════════


def test_actor_and_application_round_trip(mem_engine) -> None:
    """Insert actor + application in one session; reload each in a new session."""
    now = _now()
    actor_id = uuid.uuid4()
    app_id = uuid.uuid4()

    with Session(mem_engine) as session:
        session.add(
            Actor(
                id=actor_id,
                display_name="Round-Trip Actor",
                attuid="rt0001",
                created_at=now,
            )
        )
        # Flush the actor first — Application.created_by_id FK depends on it.
        # (No relationship() on models, so we manage FK ordering manually.)
        session.flush()
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name="Round-Trip App",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()

    with Session(mem_engine) as session:
        actor = session.get(Actor, actor_id)
        assert actor is not None, "Actor not found after commit"
        assert actor.display_name == "Round-Trip Actor"
        assert actor.attuid == "rt0001"
        assert actor.created_at is not None
        assert actor.created_at.tzinfo is not None

        app = session.get(Application, app_id)
        assert app is not None, "Application not found after commit"
        assert app.display_name == "Round-Trip App"
        assert app.state == "ACTIVE"
        assert app.row_version == 1
        assert app.created_by_id == actor_id


# ═══════════════════════════════════════════════════════════════════════════
# Test 14 — CatalogRelease + CatalogSection + CatalogQuestion round-trip
# ═══════════════════════════════════════════════════════════════════════════


def test_catalog_release_section_question_round_trip(mem_engine) -> None:
    """Insert CatalogRelease + Section + Question in one session; reload in another."""
    now = _now()
    cat_id = uuid.uuid4()
    sec_id = uuid.uuid4()
    q_id = uuid.uuid4()
    sha = _sha("d")

    with Session(mem_engine) as session:
        session.add(
            CatalogRelease(
                id=cat_id,
                semantic_version="3.0.0",
                source_filename="v3.yaml",
                source_sha256=sha,
                compiler_version="3.0",
                pub_state="PUBLISHED",
                published_at=now,
                catalog_hash=_sha("e"),
                compiler_report={"generated": True},
                created_at=now,
            )
        )
        # Flush release before section (FK dependency; no relationship() set).
        session.flush()
        session.add(
            CatalogSection(
                id=sec_id,
                release_id=cat_id,
                section_code="NET",
                display_name="Networking",
                display_order=1,
            )
        )
        # Flush section before question (FK dependency).
        session.flush()
        session.add(
            CatalogQuestion(
                id=q_id,
                section_id=sec_id,
                question_code="NET-001",
                question_text="What is the network topology?",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="MANUAL",
                condition_ast=None,
                display_order=1,
                is_active=True,
            )
        )
        session.commit()

    with Session(mem_engine) as session:
        cat = session.get(CatalogRelease, cat_id)
        assert cat is not None, "CatalogRelease not found after commit"
        assert cat.semantic_version == "3.0.0"
        assert cat.source_sha256 == sha
        assert cat.compiler_report == {"generated": True}

        sec = session.get(CatalogSection, sec_id)
        assert sec is not None, "CatalogSection not found after commit"
        assert sec.section_code == "NET"
        assert sec.release_id == cat_id

        q = session.get(CatalogQuestion, q_id)
        assert q is not None, "CatalogQuestion not found after commit"
        assert q.question_code == "NET-001"
        assert q.is_active is True
        assert q.section_id == sec_id
