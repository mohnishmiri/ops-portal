-- Migration: credential account inventory (Tools → Credential Check)
--
--   psql $DATABASE_URL -f backend/migrations/add_credential_accounts.sql
--
-- Created automatically by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band. Idempotent — safe to re-run.
--
-- One row per service account the team owns (domain account, AAF identity or
-- JFrog user), listed by application. Holds NO password or token: only the
-- owner, dates, failed-login count, reset link and notes, plus the verdict of
-- the most recent Credential Check.

CREATE TABLE IF NOT EXISTS credential_accounts (
    id                    SERIAL PRIMARY KEY,
    application           VARCHAR(200)  NOT NULL,
    app_code              VARCHAR(32),
    account_type          VARCHAR(20)   NOT NULL,
    directory             VARCHAR(32)   NOT NULL,
    account_name          VARCHAR(256)  NOT NULL,
    account_key           VARCHAR(256)  NOT NULL,
    owner                 VARCHAR(255),
    expiry_date           DATE,
    never_expires         BOOLEAN       NOT NULL DEFAULT FALSE,
    password_changed_date DATE,
    last_login_date       DATE,
    failed_logins         INTEGER,
    reset_url             VARCHAR(1000),
    notes                 TEXT,
    last_checked_at       TIMESTAMP,
    last_check_status     VARCHAR(20),
    last_checked_by       VARCHAR(255),
    created_by            VARCHAR(255),
    created_at            TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_by            VARCHAR(255),
    updated_at            TIMESTAMP     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_credential_account UNIQUE (account_type, directory, account_key)
);

CREATE INDEX IF NOT EXISTS ix_credential_accounts_application ON credential_accounts (application);
