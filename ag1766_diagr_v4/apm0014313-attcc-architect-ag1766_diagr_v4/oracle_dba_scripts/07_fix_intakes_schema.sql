-- ============================================================================
-- Migration Intake Application - Fix intakes Table
-- ============================================================================
-- Purpose: Correct intakes table column name to match ORM
-- Target: Oracle 19c or later
-- Schema: AG1766 (or MIGRATION_INTAKE_TEST)
-- Issue: DDL script had wrong column name (catalog_release_id vs catalog_id)
-- Execution: Run as schema owner
-- ============================================================================

PROMPT Fixing intakes table schema...

-- Rename catalog_release_id to catalog_id
ALTER TABLE intakes RENAME COLUMN catalog_release_id TO catalog_id;

-- Update the foreign key constraint name to match ORM
-- First drop the old constraint
ALTER TABLE intakes DROP CONSTRAINT fk_int_catr;

-- Recreate with correct name
ALTER TABLE intakes ADD CONSTRAINT fk_intk_crel 
    FOREIGN KEY (catalog_id) REFERENCES cat_releases(id);

PROMPT
PROMPT ============================================================================
PROMPT intakes schema fixed!
PROMPT 
PROMPT Changes applied:
PROMPT   - catalog_release_id → catalog_id
PROMPT   - fk_int_catr → fk_intk_crel
PROMPT
PROMPT Verification:
SELECT column_name, data_type, nullable
FROM user_tab_columns
WHERE table_name = 'INTAKES'
ORDER BY column_id;

PROMPT
PROMPT ============================================================================
