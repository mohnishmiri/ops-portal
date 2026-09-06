-- Migration: Add has_private_key column to cert_certificates table
-- Run this manually if the column doesn't exist yet:
--
--   psql $DATABASE_URL -f backend/migrations/add_has_private_key.sql
--
-- This is idempotent — safe to run multiple times.

ALTER TABLE cert_certificates
  ADD COLUMN IF NOT EXISTS has_private_key BOOLEAN DEFAULT FALSE;
