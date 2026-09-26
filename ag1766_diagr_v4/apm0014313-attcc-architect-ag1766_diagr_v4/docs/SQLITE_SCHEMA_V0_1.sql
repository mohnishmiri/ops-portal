PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

-- SQLite 3.37+ is required for STRICT tables.

CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
) STRICT;

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    attuid TEXT COLLATE NOCASE UNIQUE,
    email TEXT COLLATE NOCASE UNIQUE,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    CHECK (attuid IS NOT NULL OR email IS NOT NULL)
) STRICT;

CREATE TABLE roles (
    code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('SYSTEM', 'APPLICATION', 'INTAKE', 'SECTION')),
    restricted_decision INTEGER NOT NULL DEFAULT 0 CHECK (restricted_decision IN (0, 1))
) STRICT;

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE,
    acronym TEXT NOT NULL COLLATE NOCASE,
    portfolio TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (lifecycle_state IN ('ACTIVE', 'ON_HOLD', 'ARCHIVED')),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (name),
    UNIQUE (acronym),
    CHECK ((lifecycle_state = 'ARCHIVED') = (archived_at IS NOT NULL))
) STRICT;

CREATE TABLE application_identifiers (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    identifier_type TEXT NOT NULL
        CHECK (identifier_type IN ('CORRELATION_ID', 'MOTS_ID', 'ITAP_ID', 'OTHER')),
    value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (identifier_type, normalized_value),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
) STRICT;

CREATE UNIQUE INDEX ux_application_primary_identifier_type
    ON application_identifiers(application_id, identifier_type)
    WHERE is_primary = 1 AND valid_to IS NULL;

CREATE TABLE application_role_assignments (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    role_code TEXT NOT NULL REFERENCES roles(code),
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    assigned_by TEXT NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL,
    UNIQUE (application_id, user_id, role_code, effective_from),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
) STRICT;

CREATE UNIQUE INDEX ux_primary_application_role
    ON application_role_assignments(application_id, role_code)
    WHERE is_primary = 1 AND effective_to IS NULL;

CREATE TABLE catalog_releases (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'PUBLISHED', 'RETIRED')),
    source_file_name TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    compiler_version TEXT NOT NULL,
    compiler_report_json TEXT NOT NULL CHECK (json_valid(compiler_report_json)),
    published_by TEXT REFERENCES users(id),
    published_at TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        (status = 'DRAFT' AND published_at IS NULL) OR
        (status IN ('PUBLISHED', 'RETIRED') AND published_at IS NOT NULL)
    )
) STRICT;

CREATE TABLE catalog_sections (
    id TEXT PRIMARY KEY,
    catalog_release_id TEXT NOT NULL REFERENCES catalog_releases(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    default_owner_role_code TEXT REFERENCES roles(code),
    UNIQUE (catalog_release_id, code),
    UNIQUE (catalog_release_id, display_order)
) STRICT;

CREATE TABLE register_definitions (
    id TEXT PRIMARY KEY,
    catalog_release_id TEXT NOT NULL REFERENCES catalog_releases(id) ON DELETE CASCADE,
    register_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    schema_json TEXT NOT NULL CHECK (json_valid(schema_json)),
    stable_key_fields_json TEXT NOT NULL CHECK (json_valid(stable_key_fields_json)),
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    UNIQUE (catalog_release_id, register_key)
) STRICT;

CREATE TABLE question_definitions (
    id TEXT PRIMARY KEY,
    catalog_release_id TEXT NOT NULL REFERENCES catalog_releases(id) ON DELETE CASCADE,
    question_code TEXT NOT NULL,
    section_id TEXT NOT NULL REFERENCES catalog_sections(id),
    display_text TEXT NOT NULL,
    help_text TEXT,
    collection_mode TEXT NOT NULL
        CHECK (collection_mode IN ('AUTO_IMPORT', 'HITL_OWNER', 'HITL_PORTAL', 'ARCHITECT_DECISION', 'DERIVED')),
    response_type TEXT NOT NULL,
    response_schema_json TEXT NOT NULL CHECK (json_valid(response_schema_json)),
    required_level TEXT NOT NULL CHECK (required_level IN ('REQUIRED', 'CONDITIONAL', 'OPTIONAL')),
    required_condition_json TEXT CHECK (required_condition_json IS NULL OR json_valid(required_condition_json)),
    default_owner_role_code TEXT REFERENCES roles(code),
    sensitivity TEXT NOT NULL DEFAULT 'INTERNAL'
        CHECK (sensitivity IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')),
    freshness_days INTEGER CHECK (freshness_days IS NULL OR freshness_days > 0),
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    editable INTEGER NOT NULL CHECK (editable IN (0, 1)),
    register_definition_id TEXT REFERENCES register_definitions(id),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE (catalog_release_id, question_code),
    UNIQUE (section_id, display_order),
    CHECK (required_level != 'CONDITIONAL' OR required_condition_json IS NOT NULL),
    CHECK (collection_mode NOT IN ('DERIVED') OR editable = 0),
    CHECK (register_definition_id IS NULL OR editable = 0)
) STRICT;

CREATE TABLE question_options (
    id TEXT PRIMARY KEY,
    question_definition_id TEXT NOT NULL REFERENCES question_definitions(id) ON DELETE CASCADE,
    value TEXT NOT NULL,
    display_text TEXT NOT NULL,
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE (question_definition_id, value),
    UNIQUE (question_definition_id, display_order)
) STRICT;

CREATE TABLE question_dependencies (
    id TEXT PRIMARY KEY,
    question_definition_id TEXT NOT NULL REFERENCES question_definitions(id) ON DELETE CASCADE,
    depends_on_question_definition_id TEXT REFERENCES question_definitions(id),
    depends_on_deliverable TEXT CHECK (depends_on_deliverable IN ('TOPOLOGY', 'ADS', 'DDD')),
    dependency_kind TEXT NOT NULL CHECK (dependency_kind IN ('APPLICABILITY', 'VALIDATION', 'INVALIDATION')),
    CHECK (
        (depends_on_question_definition_id IS NOT NULL) !=
        (depends_on_deliverable IS NOT NULL)
    ),
    UNIQUE (question_definition_id, depends_on_question_definition_id, depends_on_deliverable, dependency_kind)
) STRICT;

CREATE UNIQUE INDEX ux_question_dependency_question
    ON question_dependencies(
        question_definition_id,
        depends_on_question_definition_id,
        dependency_kind
    )
    WHERE depends_on_question_definition_id IS NOT NULL;

CREATE UNIQUE INDEX ux_question_dependency_deliverable
    ON question_dependencies(
        question_definition_id,
        depends_on_deliverable,
        dependency_kind
    )
    WHERE depends_on_deliverable IS NOT NULL;

CREATE TABLE question_sources (
    question_definition_id TEXT NOT NULL REFERENCES question_definitions(id) ON DELETE CASCADE,
    source_code TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK (priority > 0),
    PRIMARY KEY (question_definition_id, source_code),
    UNIQUE (question_definition_id, priority)
) STRICT;

CREATE TABLE question_owner_roles (
    question_definition_id TEXT NOT NULL REFERENCES question_definitions(id) ON DELETE CASCADE,
    role_code TEXT NOT NULL REFERENCES roles(code),
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('PRIMARY', 'COLLABORATOR', 'REVIEWER')),
    PRIMARY KEY (question_definition_id, role_code, owner_kind)
) STRICT;

CREATE TABLE question_output_mappings (
    id TEXT PRIMARY KEY,
    question_definition_id TEXT NOT NULL REFERENCES question_definitions(id) ON DELETE CASCADE,
    deliverable TEXT NOT NULL CHECK (deliverable IN ('TOPOLOGY', 'ADS', 'DDD')),
    destination_key TEXT NOT NULL,
    mapping_json TEXT NOT NULL CHECK (json_valid(mapping_json)),
    UNIQUE (question_definition_id, deliverable, destination_key)
) STRICT;

CREATE TABLE intakes (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    catalog_release_id TEXT NOT NULL REFERENCES catalog_releases(id),
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    based_on_intake_id TEXT REFERENCES intakes(id),
    wave_assignment TEXT,
    target_date TEXT,
    workflow_state TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (workflow_state IN (
            'DRAFT', 'COLLECTING', 'READY_FOR_SECTION_REVIEW', 'SECTION_REVIEW',
            'CHANGES_REQUESTED', 'READY_FOR_ARCHITECT_REVIEW', 'ARCHITECT_REVIEW',
            'APPROVED', 'SUPERSEDED', 'CANCELLED'
        )),
    frozen_at TEXT,
    snapshot_sha256 TEXT CHECK (snapshot_sha256 IS NULL OR length(snapshot_sha256) = 64),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (application_id, revision_number),
    CHECK (
        (workflow_state IN ('APPROVED', 'SUPERSEDED')) =
        (frozen_at IS NOT NULL)
    ),
    CHECK ((frozen_at IS NULL) = (snapshot_sha256 IS NULL))
) STRICT;

CREATE UNIQUE INDEX ux_application_one_open_intake
    ON intakes(application_id)
    WHERE workflow_state NOT IN ('APPROVED', 'SUPERSEDED', 'CANCELLED');

CREATE TABLE intake_snapshots (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL UNIQUE REFERENCES intakes(id),
    catalog_release_id TEXT NOT NULL REFERENCES catalog_releases(id),
    schema_version TEXT NOT NULL,
    canonical_json TEXT NOT NULL CHECK (json_valid(canonical_json)),
    sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE snapshot_facts (
    id TEXT PRIMARY KEY,
    intake_snapshot_id TEXT NOT NULL REFERENCES intake_snapshots(id) ON DELETE CASCADE,
    canonical_path TEXT NOT NULL,
    scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    data_type TEXT NOT NULL,
    confidence TEXT NOT NULL
        CHECK (confidence IN ('OPERATOR', 'SYSTEM', 'STATED', 'DERIVED_UNVERIFIED', 'OBSERVED')),
    evidence_lineage_json TEXT NOT NULL CHECK (json_valid(evidence_lineage_json)),
    UNIQUE (intake_snapshot_id, canonical_path, scope_json)
) STRICT;

CREATE TABLE intake_deliverables (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    deliverable TEXT NOT NULL CHECK (deliverable IN ('TOPOLOGY', 'ADS', 'DDD')),
    workflow_state TEXT NOT NULL DEFAULT 'NOT_REQUESTED'
        CHECK (workflow_state IN (
            'NOT_REQUESTED', 'BLOCKED', 'READY_TO_GENERATE', 'GENERATING',
            'GENERATED_WITH_GAPS', 'READY_FOR_REVIEW', 'CHANGES_REQUESTED',
            'APPROVED', 'REJECTED', 'FAILED', 'SUPERSEDED'
        )),
    requested INTEGER NOT NULL DEFAULT 0 CHECK (requested IN (0, 1)),
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (intake_id, deliverable),
    CHECK (
        (requested = 0 AND workflow_state = 'NOT_REQUESTED') OR
        (requested = 1 AND workflow_state != 'NOT_REQUESTED')
    )
) STRICT;

CREATE TABLE section_instances (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    catalog_section_id TEXT NOT NULL REFERENCES catalog_sections(id),
    workflow_state TEXT NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (workflow_state IN (
            'NOT_STARTED', 'IN_PROGRESS', 'BLOCKED', 'READY_FOR_REVIEW',
            'IN_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', 'NOT_APPLICABLE'
        )),
    owner_user_id TEXT REFERENCES users(id),
    reviewer_user_id TEXT REFERENCES users(id),
    due_at TEXT,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (intake_id, catalog_section_id)
) STRICT;

CREATE TABLE work_assignments (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    section_instance_id TEXT REFERENCES section_instances(id) ON DELETE CASCADE,
    assignee_user_id TEXT NOT NULL REFERENCES users(id),
    role_code TEXT NOT NULL REFERENCES roles(code),
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    due_at TEXT,
    assigned_by TEXT NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK (completed_at IS NULL OR status = 'COMPLETED')
) STRICT;

CREATE TABLE answer_instances (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    question_definition_id TEXT NOT NULL REFERENCES question_definitions(id),
    applicability TEXT NOT NULL DEFAULT 'NOT_EVALUATED'
        CHECK (applicability IN ('APPLICABLE', 'NOT_APPLICABLE', 'NOT_EVALUATED', 'ERROR')),
    value_status TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (value_status IN ('UNKNOWN', 'PROPOSED', 'KNOWN', 'CONFLICT', 'NOT_APPLICABLE')),
    review_status TEXT NOT NULL DEFAULT 'UNANSWERED'
        CHECK (review_status IN ('UNANSWERED', 'DRAFT', 'ANSWERED', 'NEEDS_EVIDENCE', 'CHANGES_REQUESTED', 'CONFIRMED')),
    current_revision_id TEXT REFERENCES answer_revisions(id),
    assigned_user_id TEXT REFERENCES users(id),
    due_at TEXT,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (intake_id, question_definition_id),
    CHECK (
        (applicability = 'NOT_APPLICABLE') =
        (value_status = 'NOT_APPLICABLE')
    )
) STRICT;

CREATE TABLE answer_revisions (
    id TEXT PRIMARY KEY,
    answer_instance_id TEXT NOT NULL REFERENCES answer_instances(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    raw_value_json TEXT CHECK (raw_value_json IS NULL OR json_valid(raw_value_json)),
    confidence TEXT NOT NULL
        CHECK (confidence IN ('OPERATOR', 'SYSTEM', 'STATED', 'DERIVED_UNVERIFIED', 'OBSERVED')),
    change_reason TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (answer_instance_id, revision_number)
) STRICT;

CREATE UNIQUE INDEX ux_answer_revision_identity
    ON answer_revisions(id, answer_instance_id);

-- Circular current-revision integrity is enforced with a composite FK.
-- SQLite requires the referenced columns to be unique, provided above.
CREATE TRIGGER trg_answer_current_revision_insert
BEFORE UPDATE OF current_revision_id ON answer_instances
WHEN NEW.current_revision_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM answer_revisions r
        WHERE r.id = NEW.current_revision_id
          AND r.answer_instance_id = NEW.id
    ) THEN RAISE(ABORT, 'current answer revision belongs to another answer') END;
END;

CREATE TRIGGER trg_answer_current_revision_on_insert
BEFORE INSERT ON answer_instances
WHEN NEW.current_revision_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'answer must be inserted before its first revision');
END;

CREATE TABLE content_blobs (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    mime_type TEXT NOT NULL,
    storage_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE evidence_items (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL
        CHECK (source_system IN (
            'UAQ', 'TSS', 'ITAP', 'SUD', 'PORT', 'DXC', 'DEEP_DIVE',
            'INTERFACE_TRACKING', 'APPLICATION_QUESTIONNAIRE', 'NAMING_STANDARD',
            'WAVE_SIZING', 'WAVE_EXECUTION', 'WAVE_CAPACITY', 'TOPOLOGY',
            'ADS_TEMPLATE', 'DDD_TEMPLATE', 'OTHER'
        )),
    title TEXT NOT NULL,
    external_record_id TEXT,
    external_url TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE evidence_versions (
    id TEXT PRIMARY KEY,
    evidence_item_id TEXT NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    original_file_name TEXT,
    content_blob_id TEXT REFERENCES content_blobs(id),
    retrieval_method TEXT NOT NULL
        CHECK (retrieval_method IN ('UPLOAD', 'PORTAL_EXPORT', 'SCREENSHOT', 'MANUAL_ENTRY', 'GENERATED', 'REFERENCE')),
    as_of_at TEXT,
    source_modified_at TEXT,
    retrieved_by TEXT REFERENCES users(id),
    retrieved_at TEXT,
    validation_state TEXT NOT NULL DEFAULT 'UPLOADED'
        CHECK (validation_state IN ('UPLOADED', 'VALIDATING', 'VALID', 'INVALID', 'STALE', 'SUPERSEDED')),
    supersedes_version_id TEXT REFERENCES evidence_versions(id),
    created_at TEXT NOT NULL,
    UNIQUE (evidence_item_id, version_number),
    CHECK (
        retrieval_method IN ('MANUAL_ENTRY', 'REFERENCE') OR
        content_blob_id IS NOT NULL
    )
) STRICT;

CREATE TABLE evidence_application_links (
    evidence_version_id TEXT NOT NULL REFERENCES evidence_versions(id) ON DELETE CASCADE,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    applicability_state TEXT NOT NULL DEFAULT 'NOT_EVALUATED'
        CHECK (applicability_state IN ('MATCHED', 'NOT_MATCHED', 'AMBIGUOUS', 'NOT_EVALUATED')),
    applicability_detail_json TEXT CHECK (applicability_detail_json IS NULL OR json_valid(applicability_detail_json)),
    evaluated_by TEXT REFERENCES users(id),
    evaluated_at TEXT,
    PRIMARY KEY (evidence_version_id, application_id),
    CHECK (
        (applicability_state = 'NOT_EVALUATED' AND evaluated_at IS NULL) OR
        (applicability_state != 'NOT_EVALUATED' AND evaluated_at IS NOT NULL)
    )
) STRICT;

CREATE TABLE intake_evidence_links (
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    evidence_version_id TEXT NOT NULL REFERENCES evidence_versions(id),
    usage_state TEXT NOT NULL
        CHECK (usage_state IN ('AVAILABLE', 'SELECTED', 'EXCLUDED', 'SUPERSEDED')),
    linked_by TEXT NOT NULL REFERENCES users(id),
    linked_at TEXT NOT NULL,
    rationale TEXT,
    PRIMARY KEY (intake_id, evidence_version_id)
) STRICT;

CREATE TABLE application_identifier_evidence_links (
    application_identifier_id TEXT NOT NULL REFERENCES application_identifiers(id) ON DELETE CASCADE,
    evidence_version_id TEXT NOT NULL REFERENCES evidence_versions(id),
    relationship TEXT NOT NULL DEFAULT 'SUPPORTS'
        CHECK (relationship IN ('SUPPORTS', 'SUPERSEDES')),
    PRIMARY KEY (application_identifier_id, evidence_version_id, relationship)
) STRICT;

CREATE TABLE answer_evidence_links (
    answer_revision_id TEXT NOT NULL REFERENCES answer_revisions(id) ON DELETE CASCADE,
    evidence_version_id TEXT NOT NULL REFERENCES evidence_versions(id),
    locator_json TEXT NOT NULL CHECK (json_valid(locator_json)),
    relationship TEXT NOT NULL
        CHECK (relationship IN ('SUPPORTS', 'CONTRADICTS', 'DERIVED_FROM', 'SUPERSEDES')),
    PRIMARY KEY (answer_revision_id, evidence_version_id, relationship)
) STRICT;

CREATE TABLE import_runs (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    evidence_version_id TEXT NOT NULL REFERENCES evidence_versions(id),
    importer_code TEXT NOT NULL,
    importer_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PENDING', 'RUNNING', 'PREVIEW_READY', 'COMMITTED', 'FAILED', 'CANCELLED')),
    diagnostics_json TEXT NOT NULL CHECK (json_valid(diagnostics_json)),
    started_by TEXT NOT NULL REFERENCES users(id),
    started_at TEXT NOT NULL,
    completed_at TEXT
) STRICT;

CREATE TABLE import_candidates (
    id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES import_runs(id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('ANSWER', 'REGISTER_ROW', 'IDENTIFIER', 'ASSIGNMENT')),
    target_key TEXT NOT NULL,
    candidate_json TEXT NOT NULL CHECK (json_valid(candidate_json)),
    source_locator_json TEXT NOT NULL CHECK (json_valid(source_locator_json)),
    confidence TEXT NOT NULL
        CHECK (confidence IN ('OPERATOR', 'SYSTEM', 'STATED', 'DERIVED_UNVERIFIED', 'OBSERVED')),
    decision TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (decision IN ('PENDING', 'ACCEPT', 'REJECT', 'CONFLICT')),
    decided_by TEXT REFERENCES users(id),
    decided_at TEXT
) STRICT;

CREATE TABLE register_instances (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    register_definition_id TEXT NOT NULL REFERENCES register_definitions(id),
    workflow_state TEXT NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (workflow_state IN (
            'NOT_STARTED', 'IN_PROGRESS', 'RECONCILIATION_REQUIRED',
            'READY_FOR_REVIEW', 'CHANGES_REQUESTED', 'COMPLETE', 'NOT_APPLICABLE'
        )),
    expected_count INTEGER CHECK (expected_count IS NULL OR expected_count >= 0),
    completed_by TEXT REFERENCES users(id),
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (intake_id, register_definition_id),
    CHECK ((workflow_state = 'COMPLETE') = (completed_at IS NOT NULL))
) STRICT;

CREATE TABLE register_rows (
    id TEXT PRIMARY KEY,
    register_instance_id TEXT NOT NULL REFERENCES register_instances(id) ON DELETE CASCADE,
    stable_key TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (lifecycle_state IN ('ACTIVE', 'REMOVED', 'SUPERSEDED')),
    reconciliation_state TEXT NOT NULL DEFAULT 'UNRECONCILED'
        CHECK (reconciliation_state IN (
            'UNRECONCILED', 'DECLARED_ONLY', 'OBSERVED_ONLY',
            'MATCHED', 'MISMATCH', 'NOT_APPLICABLE'
        )),
    current_revision_id TEXT REFERENCES register_row_revisions(id),
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (register_instance_id, stable_key)
) STRICT;

CREATE TABLE register_row_revisions (
    id TEXT PRIMARY KEY,
    register_row_id TEXT NOT NULL REFERENCES register_rows(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    source_payload_json TEXT CHECK (source_payload_json IS NULL OR json_valid(source_payload_json)),
    change_reason TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (register_row_id, revision_number),
    UNIQUE (id, register_row_id)
) STRICT;

CREATE TRIGGER trg_register_current_revision_update
BEFORE UPDATE OF current_revision_id ON register_rows
WHEN NEW.current_revision_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM register_row_revisions r
        WHERE r.id = NEW.current_revision_id
          AND r.register_row_id = NEW.id
    ) THEN RAISE(ABORT, 'current register revision belongs to another row') END;
END;

CREATE TRIGGER trg_register_current_revision_on_insert
BEFORE INSERT ON register_rows
WHEN NEW.current_revision_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'register row must be inserted before its first revision');
END;

CREATE TABLE register_row_evidence_links (
    register_row_revision_id TEXT NOT NULL REFERENCES register_row_revisions(id) ON DELETE CASCADE,
    evidence_version_id TEXT NOT NULL REFERENCES evidence_versions(id),
    locator_json TEXT NOT NULL CHECK (json_valid(locator_json)),
    relationship TEXT NOT NULL
        CHECK (relationship IN ('SUPPORTS', 'CONTRADICTS', 'DERIVED_FROM', 'SUPERSEDES')),
    PRIMARY KEY (register_row_revision_id, evidence_version_id, relationship)
) STRICT;

CREATE TABLE issues (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    stable_key TEXT NOT NULL,
    issue_type TEXT NOT NULL CHECK (issue_type IN ('CONFLICT', 'MISSING', 'UNVERIFIED', 'INVALID')),
    severity TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    workflow_state TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (workflow_state IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'ACCEPTED_RISK', 'REOPENED', 'SUPERSEDED')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    owner_user_id TEXT REFERENCES users(id),
    owner_role_code TEXT REFERENCES roles(code),
    due_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (intake_id, stable_key)
) STRICT;

CREATE TABLE issue_candidates (
    id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    confidence TEXT NOT NULL,
    evidence_version_id TEXT REFERENCES evidence_versions(id),
    source_locator_json TEXT CHECK (source_locator_json IS NULL OR json_valid(source_locator_json)),
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    UNIQUE (issue_id, display_order)
) STRICT;

CREATE TABLE issue_links (
    issue_id TEXT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    linked_type TEXT NOT NULL CHECK (linked_type IN ('ANSWER', 'REGISTER_ROW', 'SECTION', 'DELIVERABLE', 'FACT_PATH')),
    linked_id TEXT NOT NULL,
    impact TEXT NOT NULL CHECK (impact IN ('BLOCKING', 'WARNING', 'INFORMATIONAL')),
    PRIMARY KEY (issue_id, linked_type, linked_id)
) STRICT;

CREATE TABLE resolutions (
    id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL REFERENCES issues(id),
    resolution_type TEXT NOT NULL CHECK (resolution_type IN ('SELECT_CANDIDATE', 'NEW_VALUE', 'ACCEPT_RISK', 'NOT_APPLICABLE')),
    selected_value_json TEXT CHECK (selected_value_json IS NULL OR json_valid(selected_value_json)),
    rationale TEXT NOT NULL,
    evidence_reference TEXT,
    resolved_by TEXT NOT NULL REFERENCES users(id),
    resolved_at TEXT NOT NULL,
    approved_by TEXT REFERENCES users(id),
    approved_at TEXT,
    review_due_at TEXT,
    CHECK ((resolution_type = 'ACCEPT_RISK') = (review_due_at IS NOT NULL)),
    CHECK (
        resolution_type != 'ACCEPT_RISK' OR
        (approved_by IS NOT NULL AND approved_at IS NOT NULL)
    )
) STRICT;

CREATE TABLE approvals (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    section_instance_id TEXT REFERENCES section_instances(id),
    deliverable_id TEXT REFERENCES intake_deliverables(id),
    issue_id TEXT REFERENCES issues(id),
    approval_type TEXT NOT NULL CHECK (approval_type IN ('SECTION', 'INTAKE', 'DELIVERABLE', 'RISK')),
    state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (state IN ('PENDING', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'SUPERSEDED')),
    requested_by TEXT NOT NULL REFERENCES users(id),
    requested_at TEXT NOT NULL,
    decided_by TEXT REFERENCES users(id),
    decided_at TEXT,
    rationale TEXT,
    CHECK (
        (approval_type = 'SECTION' AND section_instance_id IS NOT NULL AND deliverable_id IS NULL AND issue_id IS NULL) OR
        (approval_type = 'DELIVERABLE' AND deliverable_id IS NOT NULL AND section_instance_id IS NULL AND issue_id IS NULL) OR
        (approval_type = 'RISK' AND issue_id IS NOT NULL AND section_instance_id IS NULL AND deliverable_id IS NULL) OR
        (approval_type = 'INTAKE' AND section_instance_id IS NULL AND deliverable_id IS NULL AND issue_id IS NULL)
    ),
    CHECK (
        (state = 'PENDING' AND decided_by IS NULL AND decided_at IS NULL) OR
        (state != 'PENDING' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
    )
) STRICT;

CREATE TABLE comments (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL
        CHECK (entity_type IN ('ANSWER', 'REGISTER_ROW', 'ISSUE', 'SECTION', 'DELIVERABLE', 'EVIDENCE')),
    entity_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    edited_at TEXT,
    deleted_at TEXT,
    CHECK (length(trim(body)) > 0)
) STRICT;

CREATE TABLE generation_runs (
    id TEXT PRIMARY KEY,
    intake_deliverable_id TEXT NOT NULL REFERENCES intake_deliverables(id),
    intake_snapshot_id TEXT NOT NULL REFERENCES intake_snapshots(id),
    generator_code TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    config_sha256 TEXT NOT NULL CHECK (length(config_sha256) = 64),
    template_sha256 TEXT CHECK (template_sha256 IS NULL OR length(template_sha256) = 64),
    state TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    result_state TEXT CHECK (result_state IN ('GENERATED_WITH_GAPS', 'READY_FOR_REVIEW')),
    requested_by TEXT NOT NULL REFERENCES users(id),
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_code TEXT,
    error_detail TEXT,
    CHECK (
        (state = 'SUCCEEDED' AND result_state IS NOT NULL AND completed_at IS NOT NULL) OR
        (state != 'SUCCEEDED' AND result_state IS NULL)
    )
) STRICT;

CREATE TABLE generated_artifacts (
    id TEXT PRIMARY KEY,
    generation_run_id TEXT NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    original_file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    storage_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (generation_run_id, artifact_type, original_file_name)
) STRICT;

CREATE TABLE workflow_events (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES intakes(id) ON DELETE CASCADE,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    command TEXT NOT NULL,
    rationale TEXT,
    actor_user_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    application_id TEXT REFERENCES applications(id),
    intake_id TEXT REFERENCES intakes(id),
    actor_user_id TEXT REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    request_id TEXT,
    before_json TEXT CHECK (before_json IS NULL OR json_valid(before_json)),
    after_json TEXT CHECK (after_json IS NULL OR json_valid(after_json)),
    created_at TEXT NOT NULL
) STRICT;

CREATE INDEX ix_intakes_application_state ON intakes(application_id, workflow_state);
CREATE INDEX ix_sections_owner_state ON section_instances(owner_user_id, workflow_state);
CREATE INDEX ix_answers_intake_review ON answer_instances(intake_id, review_status, applicability);
CREATE INDEX ix_evidence_source ON evidence_items(source_system, created_at);
CREATE INDEX ix_evidence_validation ON evidence_versions(validation_state, evidence_item_id);
CREATE INDEX ix_evidence_application ON evidence_application_links(application_id, applicability_state);
CREATE INDEX ix_intake_evidence ON intake_evidence_links(intake_id, usage_state);
CREATE INDEX ix_registers_intake_state ON register_instances(intake_id, workflow_state);
CREATE INDEX ix_issues_intake_state_severity ON issues(intake_id, workflow_state, severity);
CREATE INDEX ix_work_assignments_assignee ON work_assignments(assignee_user_id, status, due_at);
CREATE INDEX ix_generation_deliverable ON generation_runs(intake_deliverable_id, state);
CREATE INDEX ix_snapshot_facts_path ON snapshot_facts(intake_snapshot_id, canonical_path);
CREATE INDEX ix_audit_application_time ON audit_events(application_id, created_at);
CREATE INDEX ix_comments_entity ON comments(entity_type, entity_id, created_at);
