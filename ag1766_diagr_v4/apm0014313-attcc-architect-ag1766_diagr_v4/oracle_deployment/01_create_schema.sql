-- ============================================================================
-- Oracle Schema Creation Script
-- Migration Intake Application
-- Generated: 2026-09-11
-- ============================================================================
--
-- Purpose: Create Oracle user/schema for Migration Intake application
--
-- Prerequisites:
--   - Oracle 12c or later
--   - SYSDBA privileges to create user
--   - Appropriate tablespace available
--
-- Usage:
--   sqlplus sys/password@SERVICE as sysdba @01_create_schema.sql
--
-- ============================================================================

-- Set environment
SET ECHO ON
SET FEEDBACK ON
SET SERVEROUTPUT ON

WHENEVER SQLERROR EXIT SQL.SQLCODE

-- ============================================================================
-- 1. Create User/Schema
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Creating Migration Intake schema user...
PROMPT ============================================================================

-- Drop user if exists (for clean reinstall)
-- Comment out for production first-time deployment
-- DROP USER migration_intake CASCADE;

-- Create user
CREATE USER migration_intake IDENTIFIED BY "CHANGE_ME_IN_PRODUCTION"
  DEFAULT TABLESPACE users
  TEMPORARY TABLESPACE temp
  QUOTA UNLIMITED ON users;

PROMPT User 'migration_intake' created successfully.

-- ============================================================================
-- 2. Grant Privileges
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Granting privileges...
PROMPT ============================================================================

-- Session privileges
GRANT CREATE SESSION TO migration_intake;
GRANT CREATE TABLE TO migration_intake;
GRANT CREATE SEQUENCE TO migration_intake;
GRANT CREATE VIEW TO migration_intake;
GRANT CREATE PROCEDURE TO migration_intake;
GRANT CREATE TRIGGER TO migration_intake;

-- Object privileges (for Alembic version table)
GRANT SELECT, INSERT, UPDATE, DELETE ON migration_intake.* TO migration_intake;

PROMPT Privileges granted successfully.

-- ============================================================================
-- 3. Verify User Creation
-- ============================================================================

PROMPT
PROMPT ============================================================================
PROMPT Verifying user creation...
PROMPT ============================================================================

SELECT username, account_status, default_tablespace, temporary_tablespace
FROM dba_users
WHERE username = 'MIGRATION_INTAKE';

PROMPT
PROMPT ============================================================================
PROMPT Schema creation complete!
PROMPT ============================================================================
PROMPT
PROMPT Next steps:
PROMPT   1. Update password: ALTER USER migration_intake IDENTIFIED BY "your_secure_password";
PROMPT   2. Set DATABASE_URL environment variable
PROMPT   3. Run Alembic migrations: alembic upgrade head
PROMPT ============================================================================

EXIT;
