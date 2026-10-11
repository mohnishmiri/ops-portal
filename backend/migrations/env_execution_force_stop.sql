-- Migration: force stop for running Environment Scheduler sequences.
--
--   psql $DATABASE_URL -f backend/migrations/env_execution_force_stop.sql
--
-- Idempotent. A stop is a request on the row, honoured by whichever replica
-- runs the sequence.

ALTER TABLE environment_execution_history ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMP;
ALTER TABLE environment_execution_history ADD COLUMN IF NOT EXISTS cancel_requested_by VARCHAR(255);
ALTER TABLE environment_execution_history ADD COLUMN IF NOT EXISTS cancel_rollback BOOLEAN NOT NULL DEFAULT FALSE;
