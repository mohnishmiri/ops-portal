-- Migration: whether an inventory account can sign in at all
--
--   psql $DATABASE_URL -f backend/migrations/credential_accounts_account_status.sql
--
-- A fresh database gets the column from Base.metadata.create_all; this adds it
-- to a credential_accounts table created before it existed. Idempotent.
--
-- active | inactive | disabled | locked | expired, read from Active Directory.
-- Separate from last_check_status: that one is the verdict on one password at
-- one moment, this one is the state of the account itself.

ALTER TABLE credential_accounts ADD COLUMN IF NOT EXISTS account_status VARCHAR(20);
