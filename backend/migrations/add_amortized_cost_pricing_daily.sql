-- Migration: daily amortized cost by pricing model / charge type
--
--   psql $DATABASE_URL -f backend/migrations/add_amortized_cost_pricing_daily.sql
--
-- Created automatically by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band. Idempotent — safe to re-run.
--
-- Azure's Query API allows two grouping dimensions, so resource-level rows in
-- amortized_cost_records can't carry the pricing model. This rollup feeds the
-- commitment-coverage figures, and its daily totals are the reference each
-- synced range is reconciled against before it is written.
--
-- After deploying, the next scheduled amortized sync refetches every day that
-- has cost rows but no pricing rows (one-time; ~45 min for two subscriptions
-- over 12 months), which also restores full-precision totals for those days.

CREATE TABLE IF NOT EXISTS amortized_cost_pricing_daily (
    id              SERIAL PRIMARY KEY,
    cost_date       VARCHAR(10)      NOT NULL,
    subscription_id VARCHAR(50)      NOT NULL,
    pricing_model   VARCHAR(50)      NOT NULL DEFAULT '',
    charge_type     VARCHAR(50)      NOT NULL DEFAULT '',
    cost_amount     DOUBLE PRECISION NOT NULL DEFAULT 0,
    currency        VARCHAR(10)      NOT NULL DEFAULT 'USD',
    synced_at       TIMESTAMP        NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_amortized_cost_pricing_daily_cost_date ON amortized_cost_pricing_daily (cost_date);
CREATE INDEX IF NOT EXISTS ix_amortized_cost_pricing_daily_subscription_id ON amortized_cost_pricing_daily (subscription_id);
CREATE INDEX IF NOT EXISTS ix_amortized_pricing_sub_date ON amortized_cost_pricing_daily (subscription_id, cost_date);
