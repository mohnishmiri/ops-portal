# Azure Ops Portal — Backend

Production-grade FastAPI backend for Azure Ops Intelligence & Optimization.

## Quick Start

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies (creates .venv automatically)
uv sync --native-tls

# Copy env template and configure
cp .env.example .env

# Run locally
uv run uvicorn app.main:app --reload --port 8002
```

> **Corporate proxy / TLS note:** If `uv` commands fail with `UnknownIssuer`,
> ensure `SSL_CERT_FILE` points to the corporate CA bundle (e.g. `C:\binary\cacert.pem`).
> The `native-tls = true` setting in `pyproject.toml [tool.uv]` is already enabled.

## Environment Variables

See `app/core/config.py` for full configuration. Key variables:

| Variable | Description | Required |
|----------|-------------|----------|
| AZURE_TENANT_ID | Azure AD tenant | Yes |
| AZURE_CLIENT_ID | App Registration client ID | Yes |
| AZURE_SUBSCRIPTION_IDS | Comma-separated subscription IDs | Yes |
| DATABASE_URL | PostgreSQL async connection string | Yes |
| SMTP_HOST | SMTP relay host | Yes (for notifications) |
| KEYVAULT_URL | Azure Key Vault URL | No |
| DEV_AUTH_BYPASS | Local-only synthetic **Super Admin** for requests with no Bearer token (`ENVIRONMENT=development` only) | No (default `false`) |
| PORTAL_BASE_URL | Public URL of the portal UI, used for links in emails | Yes in deployed envs (default `http://localhost:5177`) |
| ROLE_SUPER_ADMIN | Entra app role value for Super Admin | No (default `OpsPortal.SuperAdmin`) |
| OLLAMA_BASE_URL | Leadership advisor LLM base URL | No |
| OLLAMA_MODEL | Leadership advisor model name | No |
| AGENT_LLM_BASE_URL | Future agent assistant LLM base URL (separate from Leadership) | No |
| AGENT_LLM_MODEL | Future agent assistant model name | No |

Page/API caching uses PostgreSQL (`page_cache` table), not Redis.

## Subscription scoping

Portal data is limited to subscriptions marked **enabled** and **monitored** in the Admin panel (`admin_subscriptions` table). Resolution lives in `app/core/subscription_resolver.py` (`get_monitored_subscription_ids()`).

**Read paths** (dashboards, costs, AKS, compliance, Key Vault, optimization) call `get_scoped_subscription_ids()` from `app/core/subscription_scope.py`. Every `/api/v1` route runs `bind_subscription_scope`, which intersects:

```
monitored subscriptions ∩ subscriptions the user may read (project/app grants) ∩ subscription_ids query param
```

A user with no grant gets 403 on module APIs. Every subscription a request names (cluster ID, Key Vault, `subscription_id`) is then checked by `enforce_target_access`: read access for GET, write access for changes. See `docs/PROJECT_ACCESS.md` and `app/docs/access_control_README.md`.

**Background sync jobs** (scheduler, startup) use `get_monitored_subscription_ids()` with no override.

**Manual amortized sync** (`POST /sync-jobs`, `POST /costs/amortized/sync`): when the user's subscription picker is narrower than the full monitored set, the job payload includes `subscription_ids` and only those subscriptions are refreshed. Leadership manual sync always uses the full monitored set (shared dashboard snapshot).

### Per-user subscription picker

Each user can narrow their view without affecting others. Preferences are stored in `user_subscription_preferences` (keyed by Entra `sub`).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/available-subscriptions` | GET | The user's readable subscriptions (with project, app and tier) + saved/effective scope |
| `/api/v1/auth/subscription-scope` | GET | Current user's selection |
| `/api/v1/auth/subscription-scope` | PUT | Save `selected_subscription_ids` (empty array = everything the user may see) |

The React frontend sends `subscription_ids` as repeated query parameters on GET requests when the user has narrowed scope.

## Cost cleanup (v1.2.0)

FinOps delete APIs remove high-confidence waste after pre-delete validation:

| Endpoint | Validates | Portal access | Azure RBAC |
|----------|-----------|-------------|------------|
| `POST /api/v1/optimize/cleanup/disks` | Disk `Unattached` | `cost_resource_cleanup` capability (Write by default) + write access to the subscription | `Microsoft.Compute/disks/delete` |
| `POST /api/v1/optimize/cleanup/private-endpoints` | All connections `Disconnected` | `cost_resource_cleanup` capability (Write by default) + write access to the subscription | `Microsoft.Network/privateEndpoints/delete` |

Attempts are written to `audit_logs` with `feature: cost_cleanup`.

Copy `backend/.env.example` to `backend/.env` and adjust values for your environment.
