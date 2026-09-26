-- ============================================================================
-- Migration Intake Application - Table Creation (DDL)
-- ============================================================================
-- Purpose: Create all application tables with constraints
-- Target: Oracle 19c or later
-- Schema: MIGRATION_INTAKE_TEST
-- Version: Migration 0013 (includes legacy intake support)
-- Execution: Run as MIGRATION_INTAKE_TEST user
-- ============================================================================

-- Set session parameters
ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS';
ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF6';

PROMPT Creating Migration Intake application tables...

-- ============================================================================
-- 1. ACTORS - System users and service accounts
-- ============================================================================
CREATE TABLE actors (
    id CHAR(36) NOT NULL,
    display_name VARCHAR2(255) NOT NULL,
    attuid VARCHAR2(32),
    created_at VARCHAR2(32) NOT NULL,
    CONSTRAINT pk_actors PRIMARY KEY (id)
);

COMMENT ON TABLE actors IS 'System users and service accounts';
COMMENT ON COLUMN actors.id IS 'UUID primary key';
COMMENT ON COLUMN actors.display_name IS 'Human-readable name';
COMMENT ON COLUMN actors.attuid IS 'Enterprise user ID (optional)';
COMMENT ON COLUMN actors.created_at IS 'Creation timestamp (ISO 8601 UTC)';

-- ============================================================================
-- 2. APPLICATIONS - Subject applications under assessment
-- ============================================================================
CREATE TABLE applications (
    id CHAR(36) NOT NULL,
    state VARCHAR2(32) NOT NULL,
    display_name VARCHAR2(255) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    updated_at VARCHAR2(32) NOT NULL,
    row_version NUMBER(10) NOT NULL,
    created_by_id CHAR(36) NOT NULL,
    CONSTRAINT pk_applications PRIMARY KEY (id),
    CONSTRAINT fk_appl_act FOREIGN KEY (created_by_id) REFERENCES actors(id)
);

COMMENT ON TABLE applications IS 'Subject applications under migration assessment';
COMMENT ON COLUMN applications.state IS 'Application state (ACTIVE, ARCHIVED, etc.)';
COMMENT ON COLUMN applications.display_name IS 'Application name';
COMMENT ON COLUMN applications.row_version IS 'Optimistic concurrency control version';

-- ============================================================================
-- 3. APP_IDENTIFIERS - External identifiers for applications
-- ============================================================================
CREATE TABLE app_identifiers (
    id CHAR(36) NOT NULL,
    application_id CHAR(36) NOT NULL,
    identifier_type VARCHAR2(64) NOT NULL,
    raw_value VARCHAR2(255) NOT NULL,
    normalized_value VARCHAR2(255) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    CONSTRAINT pk_app_identifiers PRIMARY KEY (id),
    CONSTRAINT fk_appi_appl FOREIGN KEY (application_id) REFERENCES applications(id),
    CONSTRAINT uq_appi_itype_norm UNIQUE (identifier_type, normalized_value)
);

COMMENT ON TABLE app_identifiers IS 'External identifiers (Correlation, MOTS, iTAP)';
COMMENT ON COLUMN app_identifiers.identifier_type IS 'Type: CORRELATION, MOTS, ITAP';
COMMENT ON COLUMN app_identifiers.raw_value IS 'Original value as provided';
COMMENT ON COLUMN app_identifiers.normalized_value IS 'Normalized for matching (uppercase, alphanumeric)';

-- ============================================================================
-- 4. CAT_RELEASES - Question catalog versions
-- ============================================================================
CREATE TABLE cat_releases (
    id CHAR(36) NOT NULL,
    semantic_version VARCHAR2(32) NOT NULL,
    source_filename VARCHAR2(255) NOT NULL,
    source_sha256 VARCHAR2(64) NOT NULL,
    compiler_version VARCHAR2(32) NOT NULL,
    pub_state VARCHAR2(32) NOT NULL,
    published_at VARCHAR2(32),
    catalog_hash VARCHAR2(64),
    compiler_report CLOB,
    created_at VARCHAR2(32) NOT NULL,
    CONSTRAINT pk_cat_releases PRIMARY KEY (id),
    CONSTRAINT uq_cat_releases_source_sha256 UNIQUE (source_sha256)
);

COMMENT ON TABLE cat_releases IS 'Question catalog versions';
COMMENT ON COLUMN cat_releases.pub_state IS 'Publication state (DRAFT, PUBLISHED, DEPRECATED)';

-- ============================================================================
-- 5. CAT_SECTIONS - Catalog sections
-- ============================================================================
CREATE TABLE cat_sections (
    id CHAR(36) NOT NULL,
    release_id CHAR(36) NOT NULL,
    section_code VARCHAR2(64) NOT NULL,
    ordinal NUMBER(10) NOT NULL,
    title VARCHAR2(255) NOT NULL,
    description CLOB,
    CONSTRAINT pk_cat_sections PRIMARY KEY (id),
    CONSTRAINT fk_cats_catr FOREIGN KEY (release_id) REFERENCES cat_releases(id),
    CONSTRAINT uq_cats_rel_code UNIQUE (release_id, section_code)
);

COMMENT ON TABLE cat_sections IS 'Catalog sections (grouping for questions)';

-- ============================================================================
-- 6. CAT_QUESTIONS - Catalog questions
-- ============================================================================
CREATE TABLE cat_questions (
    id CHAR(36) NOT NULL,
    section_id CHAR(36) NOT NULL,
    question_code VARCHAR2(64) NOT NULL,
    ordinal NUMBER(10) NOT NULL,
    prompt_text CLOB NOT NULL,
    response_type VARCHAR2(64) NOT NULL,
    response_schema CLOB,
    is_required NUMBER(1) NOT NULL,
    help_text CLOB,
    metadata CLOB,
    CONSTRAINT pk_cat_questions PRIMARY KEY (id),
    CONSTRAINT fk_catq_cats FOREIGN KEY (section_id) REFERENCES cat_sections(id),
    CONSTRAINT uq_catq_sect_code UNIQUE (section_id, question_code)
);

COMMENT ON TABLE cat_questions IS 'Catalog questions with response types';
COMMENT ON COLUMN cat_questions.response_type IS 'Response type (TEXT, BOOLEAN, SINGLE_SELECT, etc.)';
COMMENT ON COLUMN cat_questions.response_schema IS 'JSON schema for response validation';
COMMENT ON COLUMN cat_questions.is_required IS '1=required, 0=optional';

-- ============================================================================
-- 7. CAT_OPTIONS - Allowed values for controlled questions
-- ============================================================================
CREATE TABLE cat_options (
    id CHAR(36) NOT NULL,
    question_id CHAR(36) NOT NULL,
    option_code VARCHAR2(64) NOT NULL,
    ordinal NUMBER(10) NOT NULL,
    display_text VARCHAR2(255) NOT NULL,
    help_text CLOB,
    CONSTRAINT pk_cat_options PRIMARY KEY (id),
    CONSTRAINT fk_cato_catq FOREIGN KEY (question_id) REFERENCES cat_questions(id),
    CONSTRAINT uq_cato_quest_code UNIQUE (question_id, option_code)
);

COMMENT ON TABLE cat_options IS 'Allowed values for single/multi-select questions';

-- ============================================================================
-- 8. CAT_SRC_RELS - Source-to-question relationships
-- ============================================================================
CREATE TABLE cat_src_rels (
    id CHAR(36) NOT NULL,
    release_id CHAR(36) NOT NULL,
    source_code VARCHAR2(64) NOT NULL,
    question_code VARCHAR2(64) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    CONSTRAINT pk_cat_src_rels PRIMARY KEY (id),
    CONSTRAINT fk_catsr_catr FOREIGN KEY (release_id) REFERENCES cat_releases(id),
    CONSTRAINT uq_catsr_rel_src_q UNIQUE (release_id, source_code, question_code)
);

COMMENT ON TABLE cat_src_rels IS 'Maps source documents to catalog questions';

-- ============================================================================
-- 9. INTAKES - Assessment intake instances
-- ============================================================================
CREATE TABLE intakes (
    id CHAR(36) NOT NULL,
    application_id CHAR(36) NOT NULL,
    catalog_id CHAR(36) NOT NULL,
    state VARCHAR2(32) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    updated_at VARCHAR2(32) NOT NULL,
    row_version NUMBER(10) NOT NULL,
    created_by_id CHAR(36) NOT NULL,
    CONSTRAINT pk_intakes PRIMARY KEY (id),
    CONSTRAINT fk_intk_appl FOREIGN KEY (application_id) REFERENCES applications(id),
    CONSTRAINT fk_intk_crel FOREIGN KEY (catalog_id) REFERENCES cat_releases(id),
    CONSTRAINT fk_intk_act FOREIGN KEY (created_by_id) REFERENCES actors(id)
);

COMMENT ON TABLE intakes IS 'Assessment intake instances';
COMMENT ON COLUMN intakes.state IS 'Intake state (OPEN, IN_PROGRESS, COMPLETED, etc.)';
COMMENT ON COLUMN intakes.catalog_id IS 'Reference to catalog release used for this intake';

-- ============================================================================
-- 10. INT_SNAPS - Immutable intake snapshots
-- ============================================================================
CREATE TABLE int_snaps (
    id CHAR(36) NOT NULL,
    intake_id CHAR(36) NOT NULL,
    snapshot_version NUMBER(10) NOT NULL,
    snapshot_hash VARCHAR2(64) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    created_by_id CHAR(36) NOT NULL,
    CONSTRAINT pk_int_snaps PRIMARY KEY (id),
    CONSTRAINT fk_ints_int FOREIGN KEY (intake_id) REFERENCES intakes(id),
    CONSTRAINT fk_ints_act FOREIGN KEY (created_by_id) REFERENCES actors(id),
    CONSTRAINT uq_ints_int_ver UNIQUE (intake_id, snapshot_version)
);

COMMENT ON TABLE int_snaps IS 'Immutable intake snapshots for downstream consumers';

-- ============================================================================
-- 11. ANS_INSTANCES - Current answer state
-- ============================================================================
CREATE TABLE ans_instances (
    id CHAR(36) NOT NULL,
    intake_id CHAR(36) NOT NULL,
    question_code VARCHAR2(64) NOT NULL,
    revision NUMBER(10) NOT NULL,
    response_value CLOB,
    scope CLOB,
    state VARCHAR2(32) NOT NULL,
    updated_at VARCHAR2(32) NOT NULL,
    updated_by_id CHAR(36) NOT NULL,
    metadata CLOB,
    CONSTRAINT pk_ans_instances PRIMARY KEY (id),
    CONSTRAINT fk_ansi_int FOREIGN KEY (intake_id) REFERENCES intakes(id),
    CONSTRAINT fk_ansi_act FOREIGN KEY (updated_by_id) REFERENCES actors(id),
    CONSTRAINT uq_ansi_int_qcode UNIQUE (intake_id, question_code)
);

COMMENT ON TABLE ans_instances IS 'Current answer state (mutable)';
COMMENT ON COLUMN ans_instances.revision IS 'Current revision number';
COMMENT ON COLUMN ans_instances.state IS 'Answer state (DRAFT, REVIEWED, APPROVED)';

-- ============================================================================
-- 12. ANS_REVISIONS - Answer history (append-only)
-- ============================================================================
CREATE TABLE ans_revisions (
    id CHAR(36) NOT NULL,
    instance_id CHAR(36) NOT NULL,
    revision NUMBER(10) NOT NULL,
    response_value CLOB,
    scope CLOB,
    state VARCHAR2(32) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    created_by_id CHAR(36) NOT NULL,
    change_rationale CLOB,
    metadata CLOB,
    CONSTRAINT pk_ans_revisions PRIMARY KEY (id),
    CONSTRAINT fk_ansr_ansi FOREIGN KEY (instance_id) REFERENCES ans_instances(id),
    CONSTRAINT fk_ansr_act FOREIGN KEY (created_by_id) REFERENCES actors(id),
    CONSTRAINT uq_ansr_inst_rev UNIQUE (instance_id, revision)
);

COMMENT ON TABLE ans_revisions IS 'Answer history (append-only audit trail)';

-- ============================================================================
-- 13. EVIDENCE_ITEMS - Uploaded evidence files
-- ============================================================================
CREATE TABLE evidence_items (
    id CHAR(36) NOT NULL,
    application_id CHAR(36) NOT NULL,
    intake_id CHAR(36) NOT NULL,
    original_filename VARCHAR2(255) NOT NULL,
    media_type VARCHAR2(128) NOT NULL,
    size_bytes NUMBER(19) NOT NULL,
    sha256 VARCHAR2(64) NOT NULL,
    storage_key VARCHAR2(512) NOT NULL,
    state VARCHAR2(32) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    created_by_id CHAR(36) NOT NULL,
    CONSTRAINT pk_evidence_items PRIMARY KEY (id),
    CONSTRAINT fk_evi_appl FOREIGN KEY (application_id) REFERENCES applications(id),
    CONSTRAINT fk_evi_int FOREIGN KEY (intake_id) REFERENCES intakes(id),
    CONSTRAINT fk_evi_act FOREIGN KEY (created_by_id) REFERENCES actors(id)
);

COMMENT ON TABLE evidence_items IS 'Uploaded evidence files';
COMMENT ON COLUMN evidence_items.sha256 IS 'SHA-256 hash for deduplication';
COMMENT ON COLUMN evidence_items.storage_key IS 'Filesystem storage path';

-- ============================================================================
-- 14. IMPORT_RUNS - Import processing runs
-- ============================================================================
CREATE TABLE import_runs (
    id CHAR(36) NOT NULL,
    application_id CHAR(36) NOT NULL,
    intake_id CHAR(36) NOT NULL,
    evidence_item_id CHAR(36) NOT NULL,
    contract_name VARCHAR2(128) NOT NULL,
    parser_version VARCHAR2(32) NOT NULL,
    state VARCHAR2(32) NOT NULL,
    identity_decision VARCHAR2(32),
    source_identity_raw VARCHAR2(255),
    source_identity_normalized VARCHAR2(255),
    identity_detail CLOB,
    total_candidates NUMBER(10),
    total_findings NUMBER(10),
    created_at VARCHAR2(32) NOT NULL,
    completed_at VARCHAR2(32),
    created_by_id CHAR(36) NOT NULL,
    import_lane VARCHAR2(30),
    matched_identifier_type VARCHAR2(20),
    CONSTRAINT pk_import_runs PRIMARY KEY (id),
    CONSTRAINT fk_impr_appl FOREIGN KEY (application_id) REFERENCES applications(id),
    CONSTRAINT fk_impr_int FOREIGN KEY (intake_id) REFERENCES intakes(id),
    CONSTRAINT fk_impr_evi FOREIGN KEY (evidence_item_id) REFERENCES evidence_items(id),
    CONSTRAINT fk_impr_act FOREIGN KEY (created_by_id) REFERENCES actors(id)
);

COMMENT ON TABLE import_runs IS 'Import processing runs';
COMMENT ON COLUMN import_runs.contract_name IS 'Document contract/format identifier';
COMMENT ON COLUMN import_runs.identity_decision IS 'Identity resolution outcome';
COMMENT ON COLUMN import_runs.import_lane IS 'Import lane: SOURCE_DOCUMENT, GAP_WORKBOOK, LEGACY_INTAKE';
COMMENT ON COLUMN import_runs.matched_identifier_type IS 'Matched identifier type: CORRELATION, MOTS, ITAP';

-- ============================================================================
-- 15. IMPORT_SHEET_RESULTS - Per-sheet import results
-- ============================================================================
CREATE TABLE import_sheet_results (
    id CHAR(36) NOT NULL,
    run_id CHAR(36) NOT NULL,
    sheet_name VARCHAR2(128) NOT NULL,
    outcome VARCHAR2(32) NOT NULL,
    proposal_count NUMBER(10) NOT NULL,
    finding_count NUMBER(10) NOT NULL,
    CONSTRAINT pk_import_sheet_results PRIMARY KEY (id),
    CONSTRAINT fk_impsr_impr FOREIGN KEY (run_id) REFERENCES import_runs(id),
    CONSTRAINT uq_impsr_run_sheet UNIQUE (run_id, sheet_name)
);

COMMENT ON TABLE import_sheet_results IS 'Per-sheet import results';

-- ============================================================================
-- 16. IMPORT_FINDINGS - Import issues and warnings
-- ============================================================================
CREATE TABLE import_findings (
    id CHAR(36) NOT NULL,
    run_id CHAR(36) NOT NULL,
    sheet_name VARCHAR2(128),
    finding_type VARCHAR2(64) NOT NULL,
    severity VARCHAR2(32) NOT NULL,
    source_locator VARCHAR2(512),
    detail CLOB,
    CONSTRAINT pk_import_findings PRIMARY KEY (id),
    CONSTRAINT fk_impf_impr FOREIGN KEY (run_id) REFERENCES import_runs(id)
);

COMMENT ON TABLE import_findings IS 'Import issues and warnings';
COMMENT ON COLUMN import_findings.severity IS 'Severity: ERROR, WARNING, INFO';

-- ============================================================================
-- 17. CANDIDATES - Proposed answer updates
-- ============================================================================
CREATE TABLE candidates (
    id CHAR(36) NOT NULL,
    import_run_id CHAR(36) NOT NULL,
    application_id CHAR(36) NOT NULL,
    intake_id CHAR(36) NOT NULL,
    evidence_item_id CHAR(36) NOT NULL,
    target_kind VARCHAR2(32) NOT NULL,
    target_key VARCHAR2(128) NOT NULL,
    origin VARCHAR2(128) NOT NULL,
    extractor_version VARCHAR2(32) NOT NULL,
    contract_version VARCHAR2(128) NOT NULL,
    response_schema_version VARCHAR2(32),
    source_locator CLOB,
    raw_value_json CLOB,
    normalized_value_json CLOB,
    scope_json CLOB,
    confidence NUMBER(5,4) NOT NULL,
    reconciliation_outcome VARCHAR2(32) NOT NULL,
    validation_json CLOB,
    base_answer_revision NUMBER(10),
    state VARCHAR2(32) NOT NULL,
    row_version NUMBER(10) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    decided_by_id CHAR(36),
    decided_at VARCHAR2(32),
    decision_rationale CLOB,
    accepted_value_json CLOB,
    CONSTRAINT pk_candidates PRIMARY KEY (id),
    CONSTRAINT fk_cand_impr FOREIGN KEY (import_run_id) REFERENCES import_runs(id),
    CONSTRAINT fk_cand_appl FOREIGN KEY (application_id) REFERENCES applications(id),
    CONSTRAINT fk_cand_int FOREIGN KEY (intake_id) REFERENCES intakes(id),
    CONSTRAINT fk_cand_evi FOREIGN KEY (evidence_item_id) REFERENCES evidence_items(id),
    CONSTRAINT fk_cand_act FOREIGN KEY (decided_by_id) REFERENCES actors(id)
);

COMMENT ON TABLE candidates IS 'Proposed answer updates from imports';
COMMENT ON COLUMN candidates.target_kind IS 'Target type: QUESTION, REGISTER, METADATA';
COMMENT ON COLUMN candidates.state IS 'Candidate state: PROPOSED, ACCEPTED, REJECTED';
COMMENT ON COLUMN candidates.base_answer_revision IS 'Answer revision at import time (for stale detection)';

-- ============================================================================
-- 18. CANDIDATE_FINDINGS - Candidate-specific issues
-- ============================================================================
CREATE TABLE candidate_findings (
    id CHAR(36) NOT NULL,
    candidate_id CHAR(36) NOT NULL,
    finding_type VARCHAR2(64) NOT NULL,
    severity VARCHAR2(32) NOT NULL,
    detail CLOB,
    CONSTRAINT pk_candidate_findings PRIMARY KEY (id),
    CONSTRAINT fk_candf_cand FOREIGN KEY (candidate_id) REFERENCES candidates(id)
);

COMMENT ON TABLE candidate_findings IS 'Candidate-specific issues';

-- ============================================================================
-- 19. ANSWER_EVIDENCE_LINKS - Answer-to-evidence relationships
-- ============================================================================
CREATE TABLE answer_evidence_links (
    id CHAR(36) NOT NULL,
    answer_instance_id CHAR(36) NOT NULL,
    evidence_item_id CHAR(36) NOT NULL,
    link_type VARCHAR2(32) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    CONSTRAINT pk_answer_evidence_links PRIMARY KEY (id),
    CONSTRAINT fk_ael_ansi FOREIGN KEY (answer_instance_id) REFERENCES ans_instances(id),
    CONSTRAINT fk_ael_evi FOREIGN KEY (evidence_item_id) REFERENCES evidence_items(id),
    CONSTRAINT uq_ael_ansi_evi UNIQUE (answer_instance_id, evidence_item_id)
);

COMMENT ON TABLE answer_evidence_links IS 'Links answers to supporting evidence';

-- ============================================================================
-- 20. WAVE_UTIL_REVISIONS - Wave utility form versions
-- ============================================================================
CREATE TABLE wave_util_revisions (
    id CHAR(36) NOT NULL,
    application_id CHAR(36) NOT NULL,
    revision NUMBER(10) NOT NULL,
    state VARCHAR2(32) NOT NULL,
    created_at VARCHAR2(32) NOT NULL,
    created_by_id CHAR(36) NOT NULL,
    CONSTRAINT pk_wave_util_revisions PRIMARY KEY (id),
    CONSTRAINT fk_wur_appl FOREIGN KEY (application_id) REFERENCES applications(id),
    CONSTRAINT fk_wur_act FOREIGN KEY (created_by_id) REFERENCES actors(id),
    CONSTRAINT uq_wur_appl_rev UNIQUE (application_id, revision)
);

COMMENT ON TABLE wave_util_revisions IS 'Wave utility form versions';

-- ============================================================================
-- 21. WAVE_UTIL_ROWS - Wave utility data rows
-- ============================================================================
CREATE TABLE wave_util_rows (
    id CHAR(36) NOT NULL,
    revision_id CHAR(36) NOT NULL,
    row_number NUMBER(10) NOT NULL,
    data_json CLOB NOT NULL,
    CONSTRAINT pk_wave_util_rows PRIMARY KEY (id),
    CONSTRAINT fk_wutr_wur FOREIGN KEY (revision_id) REFERENCES wave_util_revisions(id),
    CONSTRAINT uq_wutr_rev_rownum UNIQUE (revision_id, row_number)
);

COMMENT ON TABLE wave_util_rows IS 'Wave utility data rows';

-- ============================================================================
-- 22. AUDIT_EVENTS - Audit trail for all changes
-- ============================================================================
CREATE TABLE audit_events (
    id CHAR(36) NOT NULL,
    entity_type VARCHAR2(64) NOT NULL,
    entity_id CHAR(36) NOT NULL,
    event_code VARCHAR2(64) NOT NULL,
    actor_id CHAR(36),
    occurred_at VARCHAR2(32) NOT NULL,
    payload CLOB,
    CONSTRAINT pk_audit_events PRIMARY KEY (id)
);

COMMENT ON TABLE audit_events IS 'Audit trail for all changes';
COMMENT ON COLUMN audit_events.actor_id IS 'Actor who performed the action (no FK to allow external actors)';
COMMENT ON COLUMN audit_events.event_code IS 'Event type code (e.g., APPLICATION_CREATED, INTAKE_OPENED)';
COMMENT ON COLUMN audit_events.payload IS 'Optional JSON payload with event-specific data';

-- ============================================================================
-- 23. ALEMBIC_VERSION - Migration version tracking
-- ============================================================================
CREATE TABLE alembic_version (
    version_num VARCHAR2(32) NOT NULL,
    CONSTRAINT pk_alembic_version PRIMARY KEY (version_num)
);

COMMENT ON TABLE alembic_version IS 'Alembic migration version tracking';

-- ============================================================================
-- Verification
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Table creation complete!
PROMPT 
PROMPT Created 23 tables:
SELECT COUNT(*) AS table_count FROM user_tables;

PROMPT
PROMPT Next step: Run 03_create_indexes.sql
PROMPT ============================================================================
