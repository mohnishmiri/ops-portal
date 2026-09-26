-- ============================================================================
-- Migration Intake Application - Index Creation
-- ============================================================================
-- Purpose: Create indexes for query performance
-- Target: Oracle 19c or later
-- Schema: MIGRATION_INTAKE_TEST
-- Execution: Run as MIGRATION_INTAKE_TEST user
-- ============================================================================

PROMPT Creating indexes for Migration Intake application...

-- ============================================================================
-- Foreign Key Indexes (for join performance and referential integrity)
-- ============================================================================

-- Applications
CREATE INDEX ix_appl_created_by ON applications(created_by_id);
CREATE INDEX ix_appl_state ON applications(state);

-- App Identifiers
CREATE INDEX ix_appi_app_id ON app_identifiers(application_id);
CREATE INDEX ix_appi_type_norm ON app_identifiers(identifier_type, normalized_value);

-- Catalog Sections
CREATE INDEX ix_cats_release ON cat_sections(release_id);

-- Catalog Questions
CREATE INDEX ix_catq_section ON cat_questions(section_id);

-- Catalog Options
CREATE INDEX ix_cato_question ON cat_options(question_id);

-- Catalog Source Relations
CREATE INDEX ix_catsr_release ON cat_src_rels(release_id);
CREATE INDEX ix_catsr_source ON cat_src_rels(source_code);
CREATE INDEX ix_catsr_question ON cat_src_rels(question_code);

-- Intakes
CREATE INDEX ix_int_app ON intakes(application_id);
CREATE INDEX ix_int_catalog ON intakes(catalog_release_id);
CREATE INDEX ix_int_created_by ON intakes(created_by_id);
CREATE INDEX ix_int_state ON intakes(state);

-- Intake Snapshots
CREATE INDEX ix_ints_intake ON int_snaps(intake_id);
CREATE INDEX ix_ints_created_by ON int_snaps(created_by_id);

-- Answer Instances
CREATE INDEX ix_ansi_intake ON ans_instances(intake_id);
CREATE INDEX ix_ansi_updated_by ON ans_instances(updated_by_id);
CREATE INDEX ix_ansi_question ON ans_instances(question_code);
CREATE INDEX ix_ansi_state ON ans_instances(state);

-- Answer Revisions
CREATE INDEX ix_ansr_instance ON ans_revisions(instance_id);
CREATE INDEX ix_ansr_created_by ON ans_revisions(created_by_id);
CREATE INDEX ix_ansr_revision ON ans_revisions(instance_id, revision);

-- Evidence Items
CREATE INDEX ix_evi_app ON evidence_items(application_id);
CREATE INDEX ix_evi_intake ON evidence_items(intake_id);
CREATE INDEX ix_evi_created_by ON evidence_items(created_by_id);
CREATE INDEX ix_evi_sha256 ON evidence_items(sha256);
CREATE INDEX ix_evi_state ON evidence_items(state);

-- Import Runs
CREATE INDEX ix_impr_app ON import_runs(application_id);
CREATE INDEX ix_impr_intake ON import_runs(intake_id);
CREATE INDEX ix_impr_evidence ON import_runs(evidence_item_id);
CREATE INDEX ix_impr_created_by ON import_runs(created_by_id);
CREATE INDEX ix_impr_state ON import_runs(state);
CREATE INDEX ix_impr_lane ON import_runs(import_lane);
CREATE INDEX ix_impr_identity ON import_runs(identity_decision);

-- Import Sheet Results
CREATE INDEX ix_impsr_run ON import_sheet_results(run_id);

-- Import Findings
CREATE INDEX ix_impf_run ON import_findings(run_id);
CREATE INDEX ix_impf_severity ON import_findings(severity);

-- Candidates
CREATE INDEX ix_cand_run ON candidates(import_run_id);
CREATE INDEX ix_cand_app ON candidates(application_id);
CREATE INDEX ix_cand_intake ON candidates(intake_id);
CREATE INDEX ix_cand_evidence ON candidates(evidence_item_id);
CREATE INDEX ix_cand_decided_by ON candidates(decided_by_id);
CREATE INDEX ix_cand_state ON candidates(state);
CREATE INDEX ix_cand_target ON candidates(target_kind, target_key);

-- Candidate Findings
CREATE INDEX ix_candf_candidate ON candidate_findings(candidate_id);

-- Answer Evidence Links
CREATE INDEX ix_ael_answer ON answer_evidence_links(answer_instance_id);
CREATE INDEX ix_ael_evidence ON answer_evidence_links(evidence_item_id);

-- Wave Util Revisions
CREATE INDEX ix_wur_app ON wave_util_revisions(application_id);
CREATE INDEX ix_wur_created_by ON wave_util_revisions(created_by_id);

-- Wave Util Rows
CREATE INDEX ix_wutr_revision ON wave_util_rows(revision_id);

-- Audit Events
CREATE INDEX ix_audit_entity ON audit_events(entity_type, entity_id);
CREATE INDEX ix_audit_actor ON audit_events(actor_id);
CREATE INDEX ix_audit_occurred ON audit_events(occurred_at);

-- ============================================================================
-- Composite Indexes (for common query patterns)
-- ============================================================================

-- Find intakes by application and state
CREATE INDEX ix_int_app_state ON intakes(application_id, state);

-- Find candidates by intake and state
CREATE INDEX ix_cand_intake_state ON candidates(intake_id, state);

-- Find import runs by application and lane
CREATE INDEX ix_impr_app_lane ON import_runs(application_id, import_lane);

-- Find evidence by application and state
CREATE INDEX ix_evi_app_state ON evidence_items(application_id, state);

-- ============================================================================
-- Verification
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Index creation complete!
PROMPT 
PROMPT Created indexes:
SELECT COUNT(*) AS index_count FROM user_indexes WHERE table_name != 'ALEMBIC_VERSION';

PROMPT
PROMPT Index summary by table:
SELECT table_name, COUNT(*) AS index_count
FROM user_indexes
WHERE table_name != 'ALEMBIC_VERSION'
GROUP BY table_name
ORDER BY table_name;

PROMPT
PROMPT Next step: Run 04_seed_data.sql
PROMPT ============================================================================
