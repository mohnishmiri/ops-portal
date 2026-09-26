-- ============================================================================
-- Migration Intake Application - Oracle Schema and User Creation
-- ============================================================================
-- Purpose: Create dedicated schema/user for Migration Intake application
-- Target: Oracle 19c or later
-- Execution: Run as SYSDBA or user with CREATE USER privilege
-- ============================================================================

-- Drop user if exists (for clean reinstall)
-- CAUTION: This will drop all objects owned by the user
-- DROP USER migration_intake_test CASCADE;

-- Create user/schema
CREATE USER migration_intake_test IDENTIFIED BY "CHANGE_THIS_PASSWORD"
  DEFAULT TABLESPACE USERS
  TEMPORARY TABLESPACE TEMP
  QUOTA UNLIMITED ON USERS;

-- Grant necessary privileges
GRANT CONNECT TO migration_intake_test;
GRANT RESOURCE TO migration_intake_test;
GRANT CREATE SESSION TO migration_intake_test;
GRANT CREATE TABLE TO migration_intake_test;
GRANT CREATE SEQUENCE TO migration_intake_test;
GRANT CREATE VIEW TO migration_intake_test;
GRANT CREATE PROCEDURE TO migration_intake_test;
GRANT CREATE TRIGGER TO migration_intake_test;

-- Grant additional privileges for application functionality
GRANT SELECT_CATALOG_ROLE TO migration_intake_test;

-- Verify user creation
SELECT username, account_status, default_tablespace, temporary_tablespace
FROM dba_users
WHERE username = 'MIGRATION_INTAKE_TEST';

PROMPT
PROMPT ============================================================================
PROMPT Schema/User 'MIGRATION_INTAKE_TEST' created successfully
PROMPT 
PROMPT IMPORTANT: Change the default password immediately!
PROMPT 
PROMPT Next step: Run 02_create_tables.sql as MIGRATION_INTAKE_TEST user
PROMPT ============================================================================
