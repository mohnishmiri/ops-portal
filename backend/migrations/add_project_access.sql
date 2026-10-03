-- Project / app / subscription access (Oct 2026).
--
-- The new tables (projects, project_apps, project_admins, portal_users,
-- access_grants, access_requests, access_request_items) are created from the
-- models by create_all, which runs before this file.  This file only adds the
-- placement columns to the existing admin_subscriptions table.

ALTER TABLE admin_subscriptions
    ADD COLUMN IF NOT EXISTS app_id INTEGER REFERENCES project_apps(id);

ALTER TABLE admin_subscriptions
    ADD COLUMN IF NOT EXISTS tier VARCHAR(10);

CREATE INDEX IF NOT EXISTS ix_admin_subscriptions_app_id ON admin_subscriptions (app_id);
