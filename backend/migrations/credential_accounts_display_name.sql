-- Migration: the directory's own name for an inventory account
--
--   psql $DATABASE_URL -f backend/migrations/credential_accounts_display_name.sql
--
-- A fresh database gets the column from Base.metadata.create_all; this adds it
-- to a credential_accounts table created before it existed. Idempotent.
--
-- Set only by a Credential Check of a domain account (AD displayName). For a
-- mechID that name usually identifies the person behind it.

ALTER TABLE credential_accounts ADD COLUMN IF NOT EXISTS display_name VARCHAR(255);
