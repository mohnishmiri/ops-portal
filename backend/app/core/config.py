"""
Application configuration via Pydantic Settings.

All sensitive values are loaded from environment variables or Azure Key Vault.
Never hardcode secrets in this file.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Application ───────────────────────────────────────────────────
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", description="development | staging | production")
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    # ── Azure AD / Entra ID ───────────────────────────────────────────
    AZURE_TENANT_ID: str = Field(default="", description="Azure AD tenant ID")
    AZURE_CLIENT_ID: str = Field(default="", description="App Registration client ID for auth")
    AZURE_CLIENT_SECRET: str = Field(
        default="",
        description="Client secret (only for local dev; use Managed Identity in prod)",
    )
    AZURE_AUTHORITY: str = ""

    @property
    def authority(self) -> str:
        return self.AZURE_AUTHORITY or f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}"

    # ── Azure Subscriptions ───────────────────────────────────────────
    AZURE_SUBSCRIPTION_IDS: str = Field(
        default="",
        description="Comma-separated list of Azure subscription IDs to monitor",
    )

    @property
    def subscription_ids(self) -> list[str]:
        return [s.strip() for s in self.AZURE_SUBSCRIPTION_IDS.split(",") if s.strip()]

    # ── Azure Key Vault ───────────────────────────────────────────────
    KEYVAULT_URL: str = Field(default="", description="Azure Key Vault URL")

    # ── Cache ───────────────────────────────────────────────────────
    CACHE_TTL_SECONDS: int = Field(default=3600, description="Default cache TTL")
    REPORT_CACHE_TTL: int = Field(default=86400, description="Report cache TTL (24h)")

    # ── Database ──────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://root:password@localhost/ops_portal",
        description="PostgreSQL async connection string",
    )
    DB_POOL_SIZE: int = Field(default=100, description="SQLAlchemy connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=50, description="SQLAlchemy max overflow")
    DB_POOL_RECYCLE: int = Field(default=1800, description="Recycle connections every 30 min")
    DB_POOL_TIMEOUT: int = Field(default=30, description="Seconds to wait for a pool connection")
    DB_ECHO: bool = Field(default=False, description="Log SQL statements")

    # ── CORS ──────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:3000", "http://localhost:5177"])

    # ── Rate Limiting ─────────────────────────────────────────────────
    RATE_LIMIT_RPM: int = Field(default=120, description="Requests per minute per client")

    # ── SMTP / Notifications ──────────────────────────────────────────
    SMTP_HOST: str = Field(default="mta01.az.3pc.att.com")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM_ADDRESS: str = Field(default="m55663-ap@mta01.att-mail.com")
    SMTP_USE_TLS: bool = Field(default=True)
    NOTIFICATION_RECIPIENTS: list[str] = Field(default=["ARISTOS-AO-EUGENE-COMM-INFRA@accenture.com"])

    # ── LLM / Ollama Advisor ─────────────────────────────────────────
    OLLAMA_BASE_URL: str = Field(
        default="https://customeraccountanalyser.test.att.com",
        description="Base URL for the Ollama-compatible generation endpoint",
    )
    OLLAMA_MODEL: str = Field(
        default="llama3.1",
        description="Default model name for leadership advisor prompts",
    )
    OLLAMA_TIMEOUT_SECONDS: int = Field(default=60, description="Timeout for Ollama advisor requests")
    OLLAMA_AUTH_HEADER_NAME: str = Field(
        default="",
        description="Optional outbound auth header name for Ollama requests",
    )
    OLLAMA_AUTH_HEADER_VALUE: str = Field(
        default="",
        description="Optional outbound auth header value for Ollama requests",
    )
    AZURE_PRICING_API_URL: str = Field(
        default="https://prices.azure.com/api/retail/prices",
        description="Official Azure Retail Prices API endpoint used for pricing enrichment",
    )
    AZURE_PRICING_TIMEOUT_SECONDS: int = Field(
        default=10,
        description="Timeout for Azure Retail Prices API requests",
    )
    AZURE_PRICING_CURRENCY_CODE: str = Field(
        default="USD",
        description="Currency code used when querying the Azure Retail Prices API",
    )

    # ── RBAC Roles ────────────────────────────────────────────────────
    ROLE_ADMIN: str = "OpsPortal.Admin"
    ROLE_WRITE: str = "OpsPortal.Write"
    ROLE_READ: str = "OpsPortal.Read"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


settings = Settings()  # type: ignore[call-arg]
