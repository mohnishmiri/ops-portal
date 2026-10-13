-- Migration: when an inventory account was last read from its directory
--
--   psql $DATABASE_URL -f backend/migrations/credential_accounts_directory_synced_at.sql
--
-- A fresh database gets the column from Base.metadata.create_all; this adds it
-- to a credential_accounts table created before it existed. Idempotent.
--
-- Separate from last_checked_at on purpose: a directory read (with the
-- portal's read-only reader account) learns an account's expiry and last
-- sign-in, but proves nothing about its password.

ALTER TABLE credential_accounts ADD COLUMN IF NOT EXISTS directory_synced_at TIMESTAMP;
