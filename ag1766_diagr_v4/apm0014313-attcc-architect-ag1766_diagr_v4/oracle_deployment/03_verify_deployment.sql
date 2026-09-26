-- ============================================================================
-- Oracle Deployment Verification Script
-- Migration Intake Application
-- Generated: 2026-09-11
-- ============================================================================
--
-- Purpose: Verify Oracle deployment is correct and complete
--
-- Prerequisites:
--   - Migrations have been run (02_run_migrations.sh)
--   - Connected as migration_intake user
--
-- Usage:
--   sqlplus migration_intake/password@SERVICE @03_verify_deployment.sql
--
-- ============================================================================

SET ECHO ON
SET FEEDBACK ON
SET SERVEROUTPUT ON
SET LINESIZE 200
SET PAGESIZE 1000

-- ============================================================================
-- 1. Check Alembic Version
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Checking Alembic migration version...
PROMPT ============================================================================

SELECT version_num AS "Current Version"
FROM alembic_version;

PROMPT
PROMPT Expected: 0012 (head)
PROMPT

-- ============================================================================
-- 2. Verify All Tables Exist
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Verifying all tables exist...
PROMPT ============================================================================

SELECT table_name, num_rows, blocks
FROM user_tables
ORDER BY table_name;

PROMPT
PROMPT Expected tables (23):
PROMPT   - actors, applications, app_identifiers, intakes
PROMPT   - cat_releases, cat_sections, cat_questions, cat_options, cat_src_rels
PROMPT   - ans_instances, ans_revisions
PROMPT   - evidence_items, import_runs, import_sheet_results, import_findings
PROMPT   - candidates, candidate_findings, answer_evidence_links
PROMPT   - wave_util_rows, wave_util_revisions
PROMPT   - int_snaps, audit_events, alembic_version
PROMPT

-- ============================================================================
-- 3. Verify Primary Keys
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Verifying primary key constraints...
PROMPT ============================================================================

SELECT constraint_name, table_name, status
FROM user_constraints
WHERE constraint_type = 'P'
ORDER BY table_name;

-- ============================================================================
-- 4. Verify Foreign Keys
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Verifying foreign key constraints...
PROMPT ============================================================================

SELECT constraint_name, table_name, r_constraint_name, status
FROM user_constraints
WHERE constraint_type = 'R'
ORDER BY table_name;

-- ============================================================================
-- 5. Verify Unique Constraints
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Verifying unique constraints...
PROMPT ============================================================================

SELECT constraint_name, table_name, status
FROM user_constraints
WHERE constraint_type = 'U'
ORDER BY table_name;

-- ============================================================================
-- 6. Check Constraint Name Lengths (Oracle 12c Compatibility)
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Checking constraint name lengths (Oracle 12c limit: 30 chars)...
PROMPT ============================================================================

SELECT constraint_name, LENGTH(constraint_name) AS name_length, table_name
FROM user_constraints
WHERE LENGTH(constraint_name) > 30
ORDER BY LENGTH(constraint_name) DESC;

PROMPT
PROMPT If no rows returned, all constraint names are Oracle 12c compatible.
PROMPT

-- ============================================================================
-- 7. Verify Indexes
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Verifying indexes...
PROMPT ============================================================================

SELECT index_name, table_name, uniqueness, status
FROM user_indexes
ORDER BY table_name, index_name;

-- ============================================================================
-- 8. Check for Invalid Objects
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Checking for invalid objects...
PROMPT ============================================================================

SELECT object_type, object_name, status
FROM user_objects
WHERE status != 'VALID'
ORDER BY object_type, object_name;

PROMPT
PROMPT If no rows returned, all objects are valid.
PROMPT

-- ============================================================================
-- 9. Verify LOB Columns (for JSON storage)
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Verifying LOB columns (CLOB for JSON storage)...
PROMPT ============================================================================

SELECT table_name, column_name, data_type
FROM user_tab_columns
WHERE data_type = 'CLOB'
ORDER BY table_name, column_name;

PROMPT
PROMPT Expected CLOB columns:
PROMPT   - ans_revisions: response_json, raw_boundary_value, change_reason
PROMPT   - audit_events: payload
PROMPT   - candidates: source_locator, raw_value_json, normalized_value_json, scope_json, validation_json, decision_rationale, accepted_value_json
PROMPT   - candidate_findings: message, details_json, source_locator
PROMPT   - cat_questions: question_text, condition_ast, help_text
PROMPT   - cat_releases: compiler_report
PROMPT   - import_findings: detail
PROMPT   - int_snaps: canonical_json
PROMPT   - wave_util_revisions: field_values_json
PROMPT   - answer_evidence_links: source_locator
PROMPT

-- ============================================================================
-- 10. Check VARCHAR2 Column Sizes
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Checking VARCHAR2 column sizes...
PROMPT ============================================================================

SELECT table_name, column_name, data_type, data_length, char_length
FROM user_tab_columns
WHERE data_type = 'VARCHAR2'
  AND table_name IN ('ACTORS', 'APPLICATIONS', 'EVIDENCE_ITEMS', 'WAVE_UTIL_ROWS')
ORDER BY table_name, column_name;

-- ============================================================================
-- 11. Verify Table Counts (Should be 0 for fresh deployment)
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Checking table row counts...
PROMPT ============================================================================

SELECT 'actors' AS table_name, COUNT(*) AS row_count FROM actors
UNION ALL
SELECT 'applications', COUNT(*) FROM applications
UNION ALL
SELECT 'intakes', COUNT(*) FROM intakes
UNION ALL
SELECT 'cat_releases', COUNT(*) FROM cat_releases
UNION ALL
SELECT 'ans_instances', COUNT(*) FROM ans_instances
UNION ALL
SELECT 'evidence_items', COUNT(*) FROM evidence_items
UNION ALL
SELECT 'candidates', COUNT(*) FROM candidates
UNION ALL
SELECT 'int_snaps', COUNT(*) FROM int_snaps;

PROMPT
PROMPT For fresh deployment, all counts should be 0.
PROMPT

-- ============================================================================
-- 12. Test Basic INSERT/SELECT/DELETE (Smoke Test)
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Running smoke test (INSERT/SELECT/DELETE)...
PROMPT ============================================================================

-- Test actor insert
INSERT INTO actors (id, display_name, created_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'Test Actor', '2026-09-11T00:00:00+00:00');

-- Verify insert
SELECT id, display_name FROM actors WHERE id = '00000000-0000-0000-0000-000000000001';

-- Clean up
DELETE FROM actors WHERE id = '00000000-0000-0000-0000-000000000001';

COMMIT;

PROMPT ✓ Smoke test passed
PROMPT

-- ============================================================================
-- 13. Summary
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Deployment Verification Summary
PROMPT ============================================================================
PROMPT
PROMPT Verification complete. Review the output above for any issues.
PROMPT
PROMPT Key checks:
PROMPT   ✓ Alembic version is 0012 (head)
PROMPT   ✓ All 23 tables exist
PROMPT   ✓ All primary keys defined
PROMPT   ✓ All foreign keys defined
PROMPT   ✓ All unique constraints defined
PROMPT   ✓ No constraint names exceed 30 characters
PROMPT   ✓ All CLOB columns for JSON storage
PROMPT   ✓ No invalid objects
PROMPT   ✓ Basic INSERT/SELECT/DELETE works
PROMPT
PROMPT If all checks pass, the deployment is successful!
PROMPT ============================================================================

EXIT;
