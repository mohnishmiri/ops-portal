-- ============================================================================
-- Migration Intake Application - Schema Verification
-- ============================================================================
-- Purpose: Verify schema installation and integrity
-- Target: Oracle 19c or later
-- Schema: MIGRATION_INTAKE_TEST
-- Execution: Run as MIGRATION_INTAKE_TEST user
-- ============================================================================

SET LINESIZE 200
SET PAGESIZE 1000
COLUMN table_name FORMAT A30
COLUMN column_name FORMAT A30
COLUMN constraint_name FORMAT A30
COLUMN index_name FORMAT A30

PROMPT
PROMPT ============================================================================
PROMPT Migration Intake Application - Schema Verification
PROMPT ============================================================================

-- ============================================================================
-- 1. Table Count
-- ============================================================================

PROMPT
PROMPT 1. TABLE COUNT (Expected: 23)
PROMPT ----------------------------------------
SELECT COUNT(*) AS table_count FROM user_tables;

SELECT table_name, num_rows
FROM user_tables
ORDER BY table_name;

-- ============================================================================
-- 2. Primary Keys
-- ============================================================================

PROMPT
PROMPT 2. PRIMARY KEYS (Expected: 23)
PROMPT ----------------------------------------
SELECT COUNT(*) AS pk_count
FROM user_constraints
WHERE constraint_type = 'P';

SELECT table_name, constraint_name
FROM user_constraints
WHERE constraint_type = 'P'
ORDER BY table_name;

-- ============================================================================
-- 3. Foreign Keys
-- ============================================================================

PROMPT
PROMPT 3. FOREIGN KEYS (Expected: ~30)
PROMPT ----------------------------------------
SELECT COUNT(*) AS fk_count
FROM user_constraints
WHERE constraint_type = 'R';

SELECT 
    c.table_name,
    c.constraint_name,
    cc.column_name,
    r.table_name AS referenced_table
FROM user_constraints c
JOIN user_cons_columns cc ON c.constraint_name = cc.constraint_name
JOIN user_constraints r ON c.r_constraint_name = r.constraint_name
WHERE c.constraint_type = 'R'
ORDER BY c.table_name, c.constraint_name;

-- ============================================================================
-- 4. Unique Constraints
-- ============================================================================

PROMPT
PROMPT 4. UNIQUE CONSTRAINTS (Expected: ~15)
PROMPT ----------------------------------------
SELECT COUNT(*) AS uq_count
FROM user_constraints
WHERE constraint_type = 'U';

SELECT table_name, constraint_name
FROM user_constraints
WHERE constraint_type = 'U'
ORDER BY table_name;

-- ============================================================================
-- 5. Indexes
-- ============================================================================

PROMPT
PROMPT 5. INDEXES (Expected: ~80)
PROMPT ----------------------------------------
SELECT COUNT(*) AS index_count
FROM user_indexes
WHERE table_name != 'ALEMBIC_VERSION';

SELECT table_name, COUNT(*) AS index_count
FROM user_indexes
WHERE table_name != 'ALEMBIC_VERSION'
GROUP BY table_name
ORDER BY table_name;

-- ============================================================================
-- 6. Column Counts by Table
-- ============================================================================

PROMPT
PROMPT 6. COLUMN COUNTS BY TABLE
PROMPT ----------------------------------------
SELECT table_name, COUNT(*) AS column_count
FROM user_tab_columns
GROUP BY table_name
ORDER BY table_name;

-- ============================================================================
-- 7. Required Seed Data
-- ============================================================================

PROMPT
PROMPT 7. SEED DATA VERIFICATION
PROMPT ----------------------------------------

PROMPT Actors (Expected: 2 - System and Default):
SELECT id, display_name, attuid FROM actors ORDER BY created_at;

PROMPT
PROMPT Alembic Version (Expected: 0013):
SELECT version_num FROM alembic_version;

PROMPT
PROMPT Applications (Expected: 0 or more):
SELECT COUNT(*) AS app_count FROM applications;

-- ============================================================================
-- 8. Table Sizes
-- ============================================================================

PROMPT
PROMPT 8. TABLE SIZES
PROMPT ----------------------------------------
SELECT 
    segment_name AS table_name,
    ROUND(bytes/1024/1024, 2) AS size_mb
FROM user_segments
WHERE segment_type = 'TABLE'
ORDER BY bytes DESC;

-- ============================================================================
-- 9. Invalid Objects
-- ============================================================================

PROMPT
PROMPT 9. INVALID OBJECTS (Expected: 0)
PROMPT ----------------------------------------
SELECT COUNT(*) AS invalid_count
FROM user_objects
WHERE status = 'INVALID';

SELECT object_name, object_type, status
FROM user_objects
WHERE status = 'INVALID'
ORDER BY object_type, object_name;

-- ============================================================================
-- 10. Constraint Validation
-- ============================================================================

PROMPT
PROMPT 10. CONSTRAINT STATUS (All should be ENABLED)
PROMPT ----------------------------------------
SELECT 
    constraint_type,
    status,
    COUNT(*) AS count
FROM user_constraints
GROUP BY constraint_type, status
ORDER BY constraint_type, status;

-- ============================================================================
-- 11. Critical Tables Column Check
-- ============================================================================

PROMPT
PROMPT 11. CRITICAL TABLES COLUMN VERIFICATION
PROMPT ----------------------------------------

PROMPT Applications table columns (Expected: 7):
SELECT column_name, data_type, nullable
FROM user_tab_columns
WHERE table_name = 'APPLICATIONS'
ORDER BY column_id;

PROMPT
PROMPT Import_runs table columns (Expected: 17):
SELECT column_name, data_type, nullable
FROM user_tab_columns
WHERE table_name = 'IMPORT_RUNS'
ORDER BY column_id;

PROMPT
PROMPT Candidates table columns (Expected: 24):
SELECT column_name, data_type, nullable
FROM user_tab_columns
WHERE table_name = 'CANDIDATES'
ORDER BY column_id;

-- ============================================================================
-- 12. Schema Summary
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT SCHEMA VERIFICATION SUMMARY
PROMPT ============================================================================
PROMPT
PROMPT Expected Counts:
PROMPT   - Tables: 23
PROMPT   - Primary Keys: 23
PROMPT   - Foreign Keys: ~30
PROMPT   - Unique Constraints: ~15
PROMPT   - Indexes: ~80
PROMPT   - Actors: 2 (System, Default)
PROMPT   - Alembic Version: 0013
PROMPT   - Invalid Objects: 0
PROMPT
PROMPT If all counts match and no invalid objects exist, the schema is ready!
PROMPT
PROMPT ============================================================================
PROMPT
PROMPT Next Steps:
PROMPT   1. Update application connection string with correct credentials
PROMPT   2. Start application and verify connectivity
PROMPT   3. Application will auto-create catalog on first startup
PROMPT   4. Create first application via web UI
PROMPT
PROMPT ============================================================================
