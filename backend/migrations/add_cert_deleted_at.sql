-- Migration: soft-delete support for certificate snapshots
--
--   psql $DATABASE_URL -f backend/migrations/add_cert_deleted_at.sql
--
-- Adds a nullable deleted_at timestamp to cert_certificates so that certs
-- removed from Keyfactor (or deleted via the portal) are preserved in the DB
-- for auditing and the "Deleted Certificates" view, rather than hard-deleted.
--
-- Idempotent — safe to re-run.

ALTER TABLE cert_certificates
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;

CREATE INDEX IF NOT EXISTS ix_cert_certs_deleted_at
    ON cert_certificates (deleted_at)
    WHERE deleted_at IS NOT NULL;
