-- Migration: certificate private-key escrow pointers
--
--   psql $DATABASE_URL -f backend/migrations/add_cert_key_escrow.sql
--
-- Created automatically by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band. Idempotent — safe to re-run.
--
-- Holds NO key material: the PFX and its password live in the escrow Key Vault
-- secret named by secret_name. Kept separate from cert_certificates because
-- that snapshot is deleted per collection on every sync.

CREATE TABLE IF NOT EXISTS cert_key_escrow (
    id              SERIAL PRIMARY KEY,
    certificate_id  INTEGER      NOT NULL,
    thumbprint      VARCHAR(100) NOT NULL,
    common_name     VARCHAR(500),
    vault_name      VARCHAR(255) NOT NULL,
    secret_name     VARCHAR(127) NOT NULL,
    not_after       VARCHAR(50),
    source          VARCHAR(20)  NOT NULL DEFAULT 'renew',
    escrowed_by     VARCHAR(255),
    escrowed_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    purged_at       TIMESTAMP,
    CONSTRAINT uq_cert_escrow_thumbprint UNIQUE (thumbprint)
);

CREATE INDEX IF NOT EXISTS ix_cert_key_escrow_certificate_id ON cert_key_escrow (certificate_id);
CREATE INDEX IF NOT EXISTS ix_cert_key_escrow_thumbprint     ON cert_key_escrow (thumbprint);
CREATE INDEX IF NOT EXISTS ix_cert_key_escrow_not_after      ON cert_key_escrow (not_after);
