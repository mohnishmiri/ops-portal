-- Create the dedicated application schema for local/CI Oracle integration tests.
-- Run this script as SYSTEM while connected to the FREEPDB1 service.
-- The password is supplied interactively by SQL*Plus and is never stored here.
--
-- Example:
--   sqlplus system@//localhost:1521/FREEPDB1 @create_test_user.sql

WHENEVER SQLERROR EXIT SQL.SQLCODE;

PROMPT Enter a password for MIGRATION_INTAKE_TEST when prompted.
ACCEPT test_password CHAR PROMPT 'Password: ' HIDE;

DECLARE
    user_count NUMBER;
BEGIN
    SELECT COUNT(*)
      INTO user_count
      FROM dba_users
     WHERE username = 'MIGRATION_INTAKE_TEST';

    IF user_count = 0 THEN
        EXECUTE IMMEDIATE
            'CREATE USER migration_intake_test IDENTIFIED BY "' ||
            REPLACE('&test_password', '"', '""') ||
            '"';
    ELSE
        EXECUTE IMMEDIATE
            'ALTER USER migration_intake_test IDENTIFIED BY "' ||
            REPLACE('&test_password', '"', '""') ||
            '"';
    END IF;
END;
/

GRANT CREATE SESSION,
      CREATE TABLE,
      CREATE VIEW,
      CREATE SEQUENCE,
      CREATE PROCEDURE,
      CREATE TRIGGER
TO migration_intake_test;

ALTER USER migration_intake_test QUOTA UNLIMITED ON USERS;

PROMPT MIGRATION_INTAKE_TEST is ready for Oracle integration tests.
EXIT;
