-- Migration: saved certificate enrollment profiles
--
--   psql $DATABASE_URL -f backend/migrations/add_cert_enrollment_profiles.sql
--
-- Created automatically by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band. Idempotent — safe to re-run.
--
-- Stores the reusable part of an enrollment request (template, CA, key
-- parameters, subject defaults, AT&T metadata) so a new request only needs a
-- common name and its SANs. Holds NO key material: the PFX password and the
-- CSR are stripped by the API before insert.
--
-- owner_user_id is '' for a profile shared with everyone, otherwise the owning
-- user's id. Empty string rather than NULL so the unique constraint still
-- applies to shared names.

CREATE TABLE IF NOT EXISTS cert_enrollment_profiles (
    id                    SERIAL PRIMARY KEY,
    name                  VARCHAR(200)  NOT NULL,
    description           TEXT,
    template              VARCHAR(500),
    certificate_authority VARCHAR(500),
    defaults              JSONB         NOT NULL DEFAULT '{}'::jsonb,
    owner_user_id         VARCHAR(255)  NOT NULL DEFAULT '',
    created_by            VARCHAR(255),
    created_at            TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_by            VARCHAR(255),
    updated_at            TIMESTAMP     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cert_enroll_profile_owner_name UNIQUE (owner_user_id, name)
);

CREATE INDEX IF NOT EXISTS ix_cert_enrollment_profiles_name ON cert_enrollment_profiles (name);
CREATE INDEX IF NOT EXISTS ix_cert_enrollment_profiles_owner_user_id ON cert_enrollment_profiles (owner_user_id);
