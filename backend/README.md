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
| DEV_AUTH_BYPASS | Local-only synthetic admin when no Bearer token | No (default `false`) |
| OLLAMA_BASE_URL | Leadership advisor LLM base URL | No |
| OLLAMA_MODEL | Leadership advisor model name | No |
| AGENT_LLM_BASE_URL | Future agent assistant LLM base URL (separate from Leadership) | No |
| AGENT_LLM_MODEL | Future agent assistant model name | No |

Page/API caching uses PostgreSQL (`page_cache` table), not Redis.

Copy `backend/.env.example` to `backend/.env` and adjust values for your environment.
