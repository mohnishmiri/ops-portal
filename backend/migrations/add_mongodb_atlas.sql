-- Migration: MongoDB Atlas start/stop schedules and operations
--
--   psql $DATABASE_URL -f backend/migrations/add_mongodb_atlas.sql
--
-- Created automatically by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band. Idempotent — safe to re-run.
--
-- Neither table holds an Atlas credential. The API key lives in the
-- MONGODB_ATLAS_PUBLIC_KEY / MONGODB_ATLAS_PRIVATE_KEY settings (Key Vault).

CREATE TABLE IF NOT EXISTS atlas_schedules (
    id                     SERIAL PRIMARY KEY,
    name                   VARCHAR(200)  NOT NULL,
    description            TEXT,
    targets                JSONB         NOT NULL,
    schedule_type          VARCHAR(20)   NOT NULL DEFAULT 'recurring',
    timezone               VARCHAR(100)  NOT NULL DEFAULT 'UTC',
    stop_cron              VARCHAR(120),
    start_cron             VARCHAR(120),
    stop_at                TIMESTAMP,
    start_at               TIMESTAMP,
    next_stop_at           TIMESTAMP,
    next_start_at          TIMESTAMP,
    skip_next_stop         BOOLEAN       NOT NULL DEFAULT FALSE,
    skip_next_start        BOOLEAN       NOT NULL DEFAULT FALSE,
    is_enabled             BOOLEAN       NOT NULL DEFAULT TRUE,
    notify_on              VARCHAR(20)   NOT NULL DEFAULT 'always',
    notification_emails    VARCHAR(1000),
    remind_minutes_before  INTEGER       NOT NULL DEFAULT 0,
    stop_reminded_for      TIMESTAMP,
    start_reminded_for     TIMESTAMP,
    last_stop_run_at       TIMESTAMP,
    last_start_run_at      TIMESTAMP,
    last_run_status        VARCHAR(20),
    created_by             VARCHAR(255)  NOT NULL,
    created_by_email       VARCHAR(255),
    created_at             TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_by             VARCHAR(255),
    updated_at             TIMESTAMP     NOT NULL DEFAULT NOW(),
    CONSTRAINT atlas_schedules_name_key UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS ix_atlas_schedules_next_stop ON atlas_schedules (is_enabled, next_stop_at);
CREATE INDEX IF NOT EXISTS ix_atlas_schedules_next_start ON atlas_schedules (is_enabled, next_start_at);

CREATE TABLE IF NOT EXISTS atlas_operations (
    id                   SERIAL PRIMARY KEY,
    action               VARCHAR(20)   NOT NULL,
    trigger              VARCHAR(20)   NOT NULL,
    schedule_id          INTEGER,
    schedule_name        VARCHAR(200),
    status               VARCHAR(20)   NOT NULL DEFAULT 'in_progress',
    targets              JSONB         NOT NULL,
    reason               VARCHAR(500),
    requested_by         VARCHAR(255)  NOT NULL,
    requested_by_email   VARCHAR(255),
    requested_at         TIMESTAMP     NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMP,
    timezone             VARCHAR(100),
    notify_on            VARCHAR(20)   NOT NULL DEFAULT 'always',
    notification_emails  VARCHAR(1000),
    notified_at          TIMESTAMP,
    lease_until          TIMESTAMP,
    error_message        TEXT
);

CREATE INDEX IF NOT EXISTS ix_atlas_operations_schedule_id ON atlas_operations (schedule_id);
CREATE INDEX IF NOT EXISTS ix_atlas_operations_status ON atlas_operations (status, lease_until);
CREATE INDEX IF NOT EXISTS ix_atlas_operations_requested_at ON atlas_operations (requested_at);
