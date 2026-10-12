-- Migration: the inventory's Owner column holds the directory's name
--
--   psql $DATABASE_URL -f backend/migrations/credential_accounts_owner_is_directory_name.sql
--
-- Owner was typed in by hand and display_name held the name a check read from
-- Active Directory. They are now one column: owner, written only by a check.
-- A name the directory gave wins over a hand-typed owner, because it is what
-- the directory actually says.
--
-- The ADD first is not a mistake: it makes the UPDATE valid on a database that
-- never had display_name (a fresh install, where it adds an empty column that
-- the DROP then removes), which keeps all three statements re-runnable.

ALTER TABLE credential_accounts ADD COLUMN IF NOT EXISTS display_name VARCHAR(255);

UPDATE credential_accounts SET owner = display_name WHERE display_name IS NOT NULL;

ALTER TABLE credential_accounts DROP COLUMN IF EXISTS display_name;
