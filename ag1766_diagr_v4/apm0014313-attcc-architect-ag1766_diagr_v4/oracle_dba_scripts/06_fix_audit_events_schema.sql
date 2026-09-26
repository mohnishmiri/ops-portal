-- ============================================================================
-- Migration Intake Application - Fix audit_events Schema
-- ============================================================================
-- Purpose: Correct audit_events table column names to match ORM
-- Target: Oracle 19c or later
-- Schema: AG1766 (or MIGRATION_INTAKE_TEST)
-- Issue: DDL script had wrong column names (event_type/detail vs event_code/payload)
-- Execution: Run as schema owner
-- ============================================================================

PROMPT Fixing audit_events table schema...

-- Rename event_type to event_code
ALTER TABLE audit_events RENAME COLUMN event_type TO event_code;

-- Rename detail to payload
ALTER TABLE audit_events RENAME COLUMN detail TO payload;

PROMPT
PROMPT ============================================================================
PROMPT audit_events schema fixed!
PROMPT 
PROMPT Columns renamed:
PROMPT   - event_type → event_code
PROMPT   - detail → payload
PROMPT
PROMPT Verification:
SELECT column_name, data_type, nullable
FROM user_tab_columns
WHERE table_name = 'AUDIT_EVENTS'
ORDER BY column_id;

PROMPT
PROMPT ============================================================================
