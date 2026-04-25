# Azure Ops Portal — Backend

Production-grade FastAPI backend for Azure Ops Intelligence & Optimization.

## Quick Start

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies (creates .venv automatically)
uv sync --native-tls

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
| REDIS_URL | Redis connection string | Yes |
| SMTP_HOST | SMTP relay host | Yes |
| KEYVAULT_URL | Azure Key Vault URL | Yes |
