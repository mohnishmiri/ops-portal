-- Migration: shared per-minute request counts for the API rate limiter
--
--   psql $DATABASE_URL -f backend/migrations/add_rate_limit_windows.sql
--
-- Created automatically by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band. Idempotent — safe to re-run.
--
-- Every uvicorn worker on every replica adds its counts here every few
-- seconds, so rate_limit_rpm limits a client across the whole deployment
-- instead of once per process. Rows older than a few minutes are deleted by
-- the workers themselves.

CREATE TABLE IF NOT EXISTS rate_limit_windows (
    client_ip     VARCHAR(64) NOT NULL,
    window_start  TIMESTAMP   NOT NULL,
    request_count INTEGER     NOT NULL DEFAULT 0,
    PRIMARY KEY (client_ip, window_start)
);

CREATE INDEX IF NOT EXISTS ix_rate_limit_windows_window_start
    ON rate_limit_windows (window_start);
