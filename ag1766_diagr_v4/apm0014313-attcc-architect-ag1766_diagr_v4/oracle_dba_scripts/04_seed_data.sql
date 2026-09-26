-- ============================================================================
-- Migration Intake Application - Seed Data (DML)
-- ============================================================================
-- Purpose: Insert required seed data for application startup
-- Target: Oracle 19c or later
-- Schema: MIGRATION_INTAKE_TEST
-- Execution: Run as MIGRATION_INTAKE_TEST user
-- ============================================================================

PROMPT Inserting seed data for Migration Intake application...

-- ============================================================================
-- 1. System Actor (required for application operations)
-- ============================================================================

INSERT INTO actors (id, display_name, attuid, created_at)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'System',
    'SYSTEM',
    TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.FF6"+00:00"')
);

COMMENT ON COLUMN actors.id IS 'System actor ID: 00000000-0000-0000-0000-000000000001';

-- ============================================================================
-- 2. Default Actor (for development/testing)
-- ============================================================================

INSERT INTO actors (id, display_name, attuid, created_at)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    'Default User',
    'DEFAULT',
    TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.FF6"+00:00"')
);

-- ============================================================================
-- 3. Alembic Version (mark schema as current)
-- ============================================================================

INSERT INTO alembic_version (version_num)
VALUES ('0013');

COMMENT ON COLUMN alembic_version.version_num IS 'Current migration version: 0013 (legacy intake support)';

-- ============================================================================
-- 4. Sample Application (optional - for testing)
-- ============================================================================

-- Uncomment to create a sample application:
/*
INSERT INTO applications (
    id,
    state,
    display_name,
    created_at,
    updated_at,
    row_version,
    created_by_id
) VALUES (
    'd048292d-ba7e-4669-b8a8-24fa287514b9',
    'ACTIVE',
    'Final Account Collections Enhancement Tool | FACET',
    TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.FF6"+00:00"'),
    TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.FF6"+00:00"'),
    1,
    '00000000-0000-0000-0000-000000000001'
);

-- Sample application identifiers
INSERT INTO app_identifiers (
    id,
    application_id,
    identifier_type,
    raw_value,
    normalized_value,
    created_at
) VALUES (
    'e1234567-89ab-cdef-0123-456789abcdef',
    'd048292d-ba7e-4669-b8a8-24fa287514b9',
    'CORRELATION',
    'FACET-2024',
    'FACET2024',
    TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.FF6"+00:00"')
);
*/

-- ============================================================================
-- Commit and Verification
-- ============================================================================

COMMIT;

PROMPT
PROMPT ============================================================================
PROMPT Seed data insertion complete!
PROMPT 
PROMPT Actors created:
SELECT id, display_name, attuid FROM actors ORDER BY created_at;

PROMPT
PROMPT Alembic version:
SELECT version_num FROM alembic_version;

PROMPT
PROMPT Applications (if any):
SELECT id, display_name, state FROM applications;

PROMPT
PROMPT ============================================================================
PROMPT 
PROMPT IMPORTANT: The application will create catalog releases and questions
PROMPT on first startup. No manual catalog data insertion is required.
PROMPT 
PROMPT Next step: Run 05_verify_schema.sql
PROMPT ============================================================================
