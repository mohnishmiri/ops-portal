-- Migration: who gets Environment Scheduler run summaries, and when.
--
--   psql $DATABASE_URL -f backend/migrations/env_scheduler_notifications.sql
--
-- Idempotent. notify_on: always | failure | never. Existing schedules keep
-- emailing every run (their behaviour until now).

ALTER TABLE environment_sequences ADD COLUMN IF NOT EXISTS notification_emails VARCHAR(1000);
ALTER TABLE environment_sequences ADD COLUMN IF NOT EXISTS notify_on VARCHAR(20) NOT NULL DEFAULT 'always';
ALTER TABLE environment_schedules ADD COLUMN IF NOT EXISTS notify_on VARCHAR(20) NOT NULL DEFAULT 'always';
