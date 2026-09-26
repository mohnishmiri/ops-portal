-- ============================================================================
-- Migration Intake Application - Drop All Tables
-- ============================================================================
-- Purpose: Clean slate - drop all tables to prepare for Alembic migration
-- Target: Oracle 19c or later
-- Schema: AG1766 (or MIGRATION_INTAKE_TEST)
-- WARNING: This destroys ALL data!
-- Execution: Run as schema owner
-- ============================================================================

PROMPT ============================================================================
PROMPT WARNING: This will DROP ALL TABLES and destroy all data!
PROMPT Press Ctrl+C now to cancel, or press Enter to continue...
PROMPT ============================================================================
PAUSE

PROMPT Dropping all Migration Intake tables...

-- Drop tables in reverse dependency order
-- Drop tables that have no incoming foreign keys first

-- Drop audit_events (no incoming FKs)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE audit_events CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: audit_events');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop alembic_version (no incoming FKs)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE alembic_version CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: alembic_version');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop wave_util_rows (FK → wave_util_revisions)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE wave_util_rows CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: wave_util_rows');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop wave_util_revisions (FK → applications, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE wave_util_revisions CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: wave_util_revisions');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop answer_evidence_links (FK → ans_instances, evidence_items)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE answer_evidence_links CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: answer_evidence_links');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop candidate_findings (FK → candidates)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE candidate_findings CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: candidate_findings');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop candidates (FK → import_runs, applications, intakes, evidence_items, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE candidates CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: candidates');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop import_findings (FK → import_runs)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE import_findings CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: import_findings');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop import_sheet_results (FK → import_runs)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE import_sheet_results CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: import_sheet_results');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop import_runs (FK → applications, intakes, evidence_items, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE import_runs CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: import_runs');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop evidence_items (FK → applications, intakes, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE evidence_items CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: evidence_items');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop ans_revisions (FK → ans_instances, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE ans_revisions CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: ans_revisions');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop ans_instances (FK → intakes, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE ans_instances CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: ans_instances');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop int_snaps (FK → intakes, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE int_snaps CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: int_snaps');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop intakes (FK → applications, cat_releases, actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE intakes CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: intakes');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop cat_src_rels (FK → cat_questions)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE cat_src_rels CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: cat_src_rels');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop cat_options (FK → cat_questions)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE cat_options CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: cat_options');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop cat_questions (FK → cat_sections)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE cat_questions CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: cat_questions');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop cat_sections (FK → cat_releases)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE cat_sections CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: cat_sections');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop cat_releases (no more incoming FKs)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE cat_releases CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: cat_releases');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop app_identifiers (FK → applications)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE app_identifiers CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: app_identifiers');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop applications (FK → actors)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE applications CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: applications');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- Drop actors (no incoming FKs)
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE actors CASCADE CONSTRAINTS';
    DBMS_OUTPUT.PUT_LINE('Dropped: actors');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

PROMPT
PROMPT ============================================================================
PROMPT All tables dropped successfully!
PROMPT 
PROMPT Verification - remaining tables:
SELECT COUNT(*) AS remaining_tables FROM user_tables;

PROMPT
PROMPT Next step: Run Alembic migrations
PROMPT   alembic upgrade head
PROMPT ============================================================================
