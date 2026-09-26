"""
ORM model classes — P02 (Initial ORM model tranche).

Design rules (Architecture sections 33–34):
- UUIDs: ``PortableUUID()`` — stored as CHAR(36); always uuid.UUID in Python.
- Timestamps: ``PortableUTC()`` — timezone-aware UTC; naive datetimes rejected.
- Decimal measurements: ``PortableDecimal(p, s)`` — floats rejected at bind.
- JSON payloads: ``CanonicalJSON()`` — sorted-key UTF-8 text.
- SHA-256 hashes: ``Sha256Hex()`` — 64-char lowercase hex, validated at bind.
- State codes: plain ``String(32)`` — NOT database-native enum types.
- Boolean: SQLAlchemy ``Boolean``.
- Oracle treats empty strings as NULL — normalise at the application layer.
- No ``ON DELETE CASCADE`` on historical/audit tables.

Table names are kept short (≤ 14 chars) so the naming convention yields
constraint names within the 30-char Oracle 12c budget.  FK constraints all
carry explicit short names (e.g. ``fk_appl_act``) to stay well within budget
regardless of column-name length.  The circular reference between
``ans_instances.current_rev_id → ans_revisions.id`` is broken with
``use_alter=True`` so ``metadata.create_all()`` can determine a valid creation
order; the application breaks the insertion cycle by inserting the instance
with ``current_rev_id=NULL``, then inserting the revision, then updating.

Column attributes are declared with ``Any`` type annotations so that mypy
strict mode's [var-annotated] rule is satisfied while preserving the classic
``Column()`` style (SQLAlchemy mypy plugin is not configured in this project).

Exported names
--------------
Actor, Application, ApplicationIdentifier, CatalogRelease, CatalogSection,
CatalogQuestion, CatalogOption, CatalogSourceRelationship, Intake,
AnswerInstance, AnswerRevision, AuditEvent
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
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
    "Actor",
    "AnswerInstance",
    "AnswerRevision",
    "Application",
    "ApplicationIdentifier",
    "AuditEvent",
    "CatalogOption",
    "CatalogQuestion",
    "CatalogRelease",
    "CatalogSection",
    "CatalogSourceRelationship",
    "Intake",
    "TemplateRelease",
]

from migration_intake.persistence.models_templates import TemplateRelease


# ─────────────────────────────────────────────────────────────────────────────
# actors
# ─────────────────────────────────────────────────────────────────────────────


class Actor(Base):
    """
    An authenticated user or system identity that performs actions.

    Table: ``actors``
    PK auto-name: ``pk_actors`` (9 chars ✓)
    """

    __tablename__ = "actors"

    id: Any = Column(PortableUUID(), primary_key=True)
    display_name: Any = Column(String(255), nullable=False)
    attuid: Any = Column(String(32), nullable=True)
    created_at: Any = Column(PortableUTC(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# applications
# ─────────────────────────────────────────────────────────────────────────────


class Application(Base):
    """
    The subject application under assessment.

    Table: ``applications``
    PK auto-name:  ``pk_applications``    (15 chars ✓)
    FK explicit:   ``fk_appl_act``        (11 chars ✓)
    """

    __tablename__ = "applications"
    __table_args__ = (
        # FK: applications.created_by_id → actors.id
        ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_appl_act",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    state: Any = Column(String(32), nullable=False)  # ApplicationState codes
    display_name: Any = Column(String(255), nullable=False)
    created_at: Any = Column(PortableUTC(), nullable=False)
    updated_at: Any = Column(PortableUTC(), nullable=False)
    row_version: Any = Column(Integer(), nullable=False, default=1)
    interface_epoch: Any = Column(Integer(), nullable=False, default=1)
    created_by_id: Any = Column(PortableUUID(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# app_identifiers
# ─────────────────────────────────────────────────────────────────────────────


class ApplicationIdentifier(Base):
    """
    External identifier (ITAP, CORRELATION, MOTS, …) for an application.

    Persisted normalised value enables case-insensitive uniqueness without
    COLLATE NOCASE (Oracle-incompatible).

    Table: ``app_identifiers``
    PK auto-name:  ``pk_app_identifiers``   (18 chars ✓)
    UQ explicit:   ``uq_appi_itype_norm``   (18 chars ✓)
    FK explicit:   ``fk_appi_appl``         (12 chars ✓)
    """

    __tablename__ = "app_identifiers"
    __table_args__ = (
        # Explicit name: auto-name uq_app_identifiers_identifier_type = 35 chars ✗
        UniqueConstraint(
            "identifier_type",
            "normalized_value",
            name="uq_appi_itype_norm",
        ),
        # FK: app_identifiers.application_id → applications.id
        ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_appi_appl",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    identifier_type: Any = Column(String(64), nullable=False)  # ITAP, CORRELATION, MOTS, …
    raw_value: Any = Column(String(255), nullable=False)
    normalized_value: Any = Column(String(255), nullable=False)
    created_at: Any = Column(PortableUTC(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# cat_releases
# ─────────────────────────────────────────────────────────────────────────────


class CatalogRelease(Base):
    """
    An immutable, versioned release of the question catalog.

    Table: ``cat_releases``
    PK auto-name:  ``pk_cat_releases``               (15 chars ✓)
    UQ auto-name:  ``uq_cat_releases_source_sha256``  (29 chars ✓)
    """

    __tablename__ = "cat_releases"
    __table_args__ = (
        # UQ auto-name: uq_cat_releases_source_sha256 = 29 chars ✓
        UniqueConstraint("source_sha256"),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    semantic_version: Any = Column(String(32), nullable=False)
    source_filename: Any = Column(String(255), nullable=False)
    source_sha256: Any = Column(Sha256Hex(), nullable=False)
    compiler_version: Any = Column(String(32), nullable=False)
    pub_state: Any = Column(String(32), nullable=False)  # DRAFT, PUBLISHED, RETIRED
    published_at: Any = Column(PortableUTC(), nullable=True)
    catalog_hash: Any = Column(Sha256Hex(), nullable=True)
    compiler_report: Any = Column(CanonicalJSON(), nullable=True)
    created_at: Any = Column(PortableUTC(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# cat_sections
# ─────────────────────────────────────────────────────────────────────────────


class CatalogSection(Base):
    """
    A logical section within a catalog release.

    Table: ``cat_sections``
    PK auto-name:  ``pk_cat_sections``           (15 chars ✓)
    UQ auto-name:  ``uq_cat_sections_release_id``  (26 chars ✓)
    FK explicit:   ``fk_csec_crel``               (12 chars ✓)
    """

    __tablename__ = "cat_sections"
    __table_args__ = (
        # UQ auto-name: uq_cat_sections_release_id = 26 chars ✓ (column_0 = release_id)
        UniqueConstraint("release_id", "section_code"),
        # FK: cat_sections.release_id → cat_releases.id
        ForeignKeyConstraint(
            ["release_id"],
            ["cat_releases.id"],
            name="fk_csec_crel",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    release_id: Any = Column(PortableUUID(), nullable=False)
    section_code: Any = Column(String(64), nullable=False)
    display_name: Any = Column(String(255), nullable=False)
    display_order: Any = Column(Integer(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# cat_questions
# ─────────────────────────────────────────────────────────────────────────────


class CatalogQuestion(Base):
    """
    A single question within a catalog section.

    Table: ``cat_questions``
    PK auto-name:  ``pk_cat_questions``            (16 chars ✓)
    UQ auto-name:  ``uq_cat_questions_section_id``  (27 chars ✓)
    FK explicit:   ``fk_cq_csec``                  (10 chars ✓)
    """

    __tablename__ = "cat_questions"
    __table_args__ = (
        # UQ auto-name: uq_cat_questions_section_id = 27 chars ✓ (column_0 = section_id)
        UniqueConstraint("section_id", "question_code"),
        # FK: cat_questions.section_id → cat_sections.id
        ForeignKeyConstraint(
            ["section_id"],
            ["cat_sections.id"],
            name="fk_cq_csec",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    section_id: Any = Column(PortableUUID(), nullable=False)
    question_code: Any = Column(String(64), nullable=False)
    question_text: Any = Column(Text(), nullable=False)
    response_type: Any = Column(String(64), nullable=False)
    required_level: Any = Column(String(32), nullable=False)
    collection_mode: Any = Column(String(32), nullable=False)
    condition_ast: Any = Column(CanonicalJSON(), nullable=True)
    display_order: Any = Column(Integer(), nullable=False)
    is_active: Any = Column(Boolean(), nullable=False, default=True)
    # P05c additions: metadata for registry editor
    help_text: Any = Column(Text(), nullable=True)
    units: Any = Column(String(32), nullable=True)
    field_name: Any = Column(String(64), nullable=True)
    response_schema_version: Any = Column(String(32), nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# cat_options
# ─────────────────────────────────────────────────────────────────────────────


class CatalogOption(Base):
    """
    A selectable option for a catalog question.

    Table: ``cat_options``
    PK auto-name:  ``pk_cat_options``             (14 chars ✓)
    UQ auto-name:  ``uq_cat_options_question_id``  (26 chars ✓)
    FK explicit:   ``fk_copt_cq``                 (10 chars ✓)
    """

    __tablename__ = "cat_options"
    __table_args__ = (
        # UQ auto-name: uq_cat_options_question_id = 26 chars ✓ (column_0 = question_id)
        UniqueConstraint("question_id", "option_code"),
        # FK: cat_options.question_id → cat_questions.id
        ForeignKeyConstraint(
            ["question_id"],
            ["cat_questions.id"],
            name="fk_copt_cq",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    question_id: Any = Column(PortableUUID(), nullable=False)
    option_code: Any = Column(String(64), nullable=False)
    display_label: Any = Column(String(255), nullable=False)
    display_order: Any = Column(Integer(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# cat_src_rels
# ─────────────────────────────────────────────────────────────────────────────


class CatalogSourceRelationship(Base):
    """
    Mapping from a catalog question to a named evidence source.

    Table: ``cat_src_rels``
    PK auto-name:  ``pk_cat_src_rels``  (15 chars ✓)
    FK explicit:   ``fk_csr_cq``        ( 9 chars ✓)
    """

    __tablename__ = "cat_src_rels"
    __table_args__ = (
        # FK: cat_src_rels.question_id → cat_questions.id
        ForeignKeyConstraint(
            ["question_id"],
            ["cat_questions.id"],
            name="fk_csr_cq",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    question_id: Any = Column(PortableUUID(), nullable=False)
    source_label: Any = Column(String(128), nullable=False)
    priority: Any = Column(Integer(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# intakes
# ─────────────────────────────────────────────────────────────────────────────


class Intake(Base):
    """
    A single intake workflow instance linking an application to a catalog release.

    Table: ``intakes``
    PK auto-name:  ``pk_intakes``    (10 chars ✓)
    FK explicit:   ``fk_intk_appl``  (12 chars ✓)
    FK explicit:   ``fk_intk_crel``  (12 chars ✓)
    FK explicit:   ``fk_intk_act``   (11 chars ✓)
    """

    __tablename__ = "intakes"
    __table_args__ = (
        # FK: intakes.application_id → applications.id
        ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_intk_appl",
        ),
        # FK: intakes.catalog_id → cat_releases.id
        ForeignKeyConstraint(
            ["catalog_id"],
            ["cat_releases.id"],
            name="fk_intk_crel",
        ),
        # FK: intakes.created_by_id → actors.id
        ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name="fk_intk_act",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    application_id: Any = Column(PortableUUID(), nullable=False)
    catalog_id: Any = Column(PortableUUID(), nullable=False)
    state: Any = Column(String(32), nullable=False)  # IntakeState codes
    created_at: Any = Column(PortableUTC(), nullable=False)
    updated_at: Any = Column(PortableUTC(), nullable=False)
    row_version: Any = Column(Integer(), nullable=False, default=1)
    content_epoch: Any = Column(Integer(), nullable=False, default=1)
    created_by_id: Any = Column(PortableUUID(), nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# ans_instances
# ─────────────────────────────────────────────────────────────────────────────


class AnswerInstance(Base):
    """
    One answer slot per (intake, question) pair.

    ``current_rev_id`` is nullable — set to NULL on first insert to break the
    circular FK with ``ans_revisions``.  The FK uses ``use_alter=True`` so
    ``metadata.create_all()`` can order the DDL correctly.

    Table: ``ans_instances``
    PK auto-name:  ``pk_ans_instances``           (16 chars ✓)
    UQ auto-name:  ``uq_ans_instances_intake_id``  (26 chars ✓)
    FK explicit:   ``fk_ainst_intk``               (13 chars ✓)
    FK explicit:   ``fk_ainst_cq``                 (11 chars ✓)
    FK explicit:   ``fk_ainst_arev`` (use_alter)   (13 chars ✓)
    """

    __tablename__ = "ans_instances"
    __table_args__ = (
        # UQ auto-name: uq_ans_instances_intake_id = 26 chars ✓ (column_0 = intake_id)
        UniqueConstraint("intake_id", "question_id"),
        # FK: ans_instances.intake_id → intakes.id
        ForeignKeyConstraint(
            ["intake_id"],
            ["intakes.id"],
            name="fk_ainst_intk",
        ),
        # FK: ans_instances.question_id → cat_questions.id
        ForeignKeyConstraint(
            ["question_id"],
            ["cat_questions.id"],
            name="fk_ainst_cq",
        ),
        # FK: ans_instances.current_rev_id → ans_revisions.id
        # use_alter=True breaks the circular dependency with ans_revisions so
        # create_all() can determine a valid DDL order.
        ForeignKeyConstraint(
            ["current_rev_id"],
            ["ans_revisions.id"],
            name="fk_ainst_arev",
            use_alter=True,
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    intake_id: Any = Column(PortableUUID(), nullable=False)
    question_id: Any = Column(PortableUUID(), nullable=False)
    created_at: Any = Column(PortableUTC(), nullable=False)
    # nullable: resolved after first revision is inserted (cycle-breaker)
    current_rev_id: Any = Column(PortableUUID(), nullable=True)
    # P05c additions: applicability, state, and concurrency
    applicability: Any = Column(String(32), nullable=False, default="APPLICABLE")
    value_state: Any = Column(String(32), nullable=False, default="EMPTY")
    review_state: Any = Column(String(32), nullable=False, default="UNREVIEWED")
    updated_at: Any = Column(PortableUTC(), nullable=False)
    row_version: Any = Column(Integer(), nullable=False, default=1)


# ─────────────────────────────────────────────────────────────────────────────
# ans_revisions
# ─────────────────────────────────────────────────────────────────────────────


class AnswerRevision(Base):
    """
    Append-only revision of a single answer instance.

    Table: ``ans_revisions``
    PK auto-name:  ``pk_ans_revisions``               (16 chars ✓)
    UQ auto-name:  ``uq_ans_revisions_instance_id``   (28 chars ✓)
    FK explicit:   ``fk_arev_ainst``                  (13 chars ✓)
    FK explicit:   ``fk_arev_act``                    (11 chars ✓)

    No ON DELETE CASCADE — revisions are historical records.
    """

    __tablename__ = "ans_revisions"
    __table_args__ = (
        # UQ auto-name: uq_ans_revisions_instance_id = 28 chars ✓ (column_0 = instance_id)
        UniqueConstraint("instance_id", "revision_number"),
        # FK: ans_revisions.instance_id → ans_instances.id
        ForeignKeyConstraint(
            ["instance_id"],
            ["ans_instances.id"],
            name="fk_arev_ainst",
        ),
        # FK: ans_revisions.authored_by_id → actors.id
        ForeignKeyConstraint(
            ["authored_by_id"],
            ["actors.id"],
            name="fk_arev_act",
        ),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    instance_id: Any = Column(PortableUUID(), nullable=False)
    revision_number: Any = Column(Integer(), nullable=False)
    response_json: Any = Column(CanonicalJSON(), nullable=False)
    confirm_state: Any = Column(String(32), nullable=False)
    authored_at: Any = Column(PortableUTC(), nullable=False)
    authored_by_id: Any = Column(PortableUUID(), nullable=False)
    # P05c additions: schema version, boundary value, and change reason
    response_schema_version: Any = Column(String(32), nullable=True)
    raw_boundary_value: Any = Column(Text(), nullable=True)
    change_reason: Any = Column(Text(), nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# audit_events
# ─────────────────────────────────────────────────────────────────────────────


class AuditEvent(Base):
    """
    Immutable audit log entry for any domain entity state change.

    ``entity_id`` and ``actor_id`` are plain PortableUUID columns without FK
    constraints — audit records must survive deletion of the referenced entity
    and may reference entities from multiple tables.

    Table: ``audit_events``
    PK auto-name:  ``pk_audit_events``              (15 chars ✓)
    IX explicit:   ``ix_audit_events_entity_type``   (28 chars ✓)
    IX explicit:   ``ix_audit_events_occurred_at``   (27 chars ✓)

    No ON DELETE CASCADE — audit rows are permanent.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # Composite index: common query pattern is entity_type + entity_id
        Index("ix_audit_events_entity_type", "entity_type", "entity_id"),
        # Time-range queries
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    entity_type: Any = Column(String(64), nullable=False)
    entity_id: Any = Column(PortableUUID(), nullable=False)
    event_code: Any = Column(String(64), nullable=False)
    actor_id: Any = Column(PortableUUID(), nullable=True)  # plain UUID, no FK
    occurred_at: Any = Column(PortableUTC(), nullable=False)
    payload: Any = Column(CanonicalJSON(), nullable=True)
