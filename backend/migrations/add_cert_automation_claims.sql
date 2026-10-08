-- Migration: once-a-day claims for certificate expiry alerts and auto-renewal
--
--   psql $DATABASE_URL -f backend/migrations/add_cert_automation_claims.sql
--
-- Created automatically by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band. Idempotent — safe to re-run.
--
-- Every uvicorn worker on every replica runs the scheduler. The unique key is
-- what lets exactly one of them send a day's report or renew a certificate.

CREATE TABLE IF NOT EXISTS cert_automation_claims (
    id          SERIAL PRIMARY KEY,
    claim_type  VARCHAR(40)  NOT NULL,
    subject_id  INTEGER      NOT NULL,
    claim_date  VARCHAR(10)  NOT NULL,
    claimed_by  VARCHAR(255),
    claimed_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cert_automation_claim UNIQUE (claim_type, subject_id, claim_date)
);

CREATE INDEX IF NOT EXISTS ix_cert_automation_claims_claimed_at ON cert_automation_claims (claimed_at);
