"""
Application configuration via Pydantic Settings.

All sensitive values are loaded from environment variables or Azure Key Vault.
Never hardcode secrets in this file.
"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Application ───────────────────────────────────────────────────
    APP_VERSION: str = "1.3.0"
    # Defaults to "production" deliberately: a missing or mis-provisioned
    # ENVIRONMENT value must never silently degrade the portal into the
    # permissive development auth path.
    ENVIRONMENT: str = Field(default="production", description="development | staging | production")
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False
    DEV_AUTH_BYPASS: bool = Field(
        default=False,
        description=(
            "When true in development ONLY, allow a synthetic admin for requests that carry "
            "no Bearer token at all. Never upgrades an invalid or expired token. Startup "
            "refuses to boot if this is set outside development."
        ),
    )

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
    # Override in backend/.env (OLLAMA_BASE_URL) or via deployment env vars.
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Base URL for the Ollama-compatible generation endpoint",
    )

    @field_validator("OLLAMA_BASE_URL")
    @classmethod
    def _strip_ollama_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

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

    # ── Agent LLM (future agentic layer — separate from Leadership Ollama) ──
    AGENT_LLM_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Base URL for the agentic assistant LLM endpoint",
    )
    AGENT_LLM_MODEL: str = Field(
        default="llama3.1",
        description="Default model for agent chat / tool orchestration",
    )
    AGENT_LLM_TIMEOUT_SECONDS: int = Field(
        default=120,
        description="Timeout for agent LLM requests",
    )
    AGENT_LLM_AUTH_HEADER_NAME: str = Field(
        default="",
        description="Optional outbound auth header name for the agent LLM proxy",
    )
    AGENT_LLM_AUTH_HEADER_VALUE: str = Field(
        default="",
        description="Optional outbound auth header value for the agent LLM proxy",
    )

    @field_validator("AGENT_LLM_BASE_URL")
    @classmethod
    def _strip_agent_llm_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

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

    # ── Kubernetes Dashboard Proxy ────────────────────────────────────
    K8S_DASHBOARD_TOKEN_PROD: str = Field(default="", description="Bearer token for Production K8s Dashboard")
    K8S_DASHBOARD_TOKEN_PREPROD: str = Field(default="", description="Bearer token for PreProd K8s Dashboard")
    K8S_DASHBOARD_TOKEN_PERF: str = Field(default="", description="Bearer token for Performance K8s Dashboard")
    K8S_DASHBOARD_TOKEN_UAT: str = Field(default="", description="Bearer token for UAT K8s Dashboard")
    K8S_DASHBOARD_TOKEN_DEV: str = Field(default="", description="Bearer token for Development K8s Dashboard")
    K8S_DASHBOARD_TOKEN_DR: str = Field(default="", description="Bearer token for DR K8s Dashboard")
    K8S_DASHBOARD_SESSION_SECRET: str = Field(
        default="",
        description="Secret used to sign K8s Dashboard launch and session tokens",
    )
    K8S_DASHBOARD_PROXY_TIMEOUT: int = Field(
        default=30, description="Timeout in seconds for proxied dashboard requests"
    )

    # ── Keyfactor Command (Certificate Lifecycle) ─────────────────────
    # Certificate management authenticates to Keyfactor via an Azure AD
    # service principal (OAuth2 client-credentials). All values are config
    # driven — never hardcode secrets or environment-specific URLs.
    KEYFACTOR_BASE_URL: str = Field(
        default="",
        description="Base URL of the Keyfactor Command instance, e.g. https://keyfactor.example.com",
    )
    KEYFACTOR_TENANT_ID: str = Field(
        default="",
        description="Azure AD tenant ID for the Keyfactor service principal (defaults to AZURE_TENANT_ID)",
    )
    KEYFACTOR_CLIENT_ID: str = Field(
        default="",
        description="Client ID of the Azure AD service principal used to obtain Keyfactor tokens",
    )
    KEYFACTOR_CLIENT_SECRET: str = Field(
        default="",
        description="Client secret of the Keyfactor service principal (source from Key Vault / env)",
    )
    KEYFACTOR_OAUTH_SCOPE: str = Field(
        default="",
        description="OAuth2 scope/resource for the Keyfactor API app registration, e.g. api://<app-id>/.default",
    )
    KEYFACTOR_TOKEN_URL: str = Field(
        default="",
        description="Optional explicit OAuth2 token endpoint. Defaults to the tenant v2.0 token endpoint.",
    )
    KEYFACTOR_API_VERSION: str = Field(
        default="1",
        description="Value for the x-keyfactor-api-version header",
    )
    KEYFACTOR_TIMEOUT_SECONDS: int = Field(
        default=30,
        description="Timeout in seconds for Keyfactor and token requests",
    )
    KEYFACTOR_VERIFY_SSL: bool = Field(
        default=True,
        description="Verify TLS certificates when calling Keyfactor",
    )
    KEYFACTOR_DEFAULT_CA: str = Field(
        default="",
        description="Optional default issuing CA (logical name) used to pre-fill enrollment",
    )
    KEYFACTOR_DEFAULT_TEMPLATE: str = Field(
        default="",
        description="Optional default certificate template short name used to pre-fill enrollment",
    )
    KEYFACTOR_LIST_CACHE_TTL: int = Field(
        default=60,
        description="Short-lived cache TTL (seconds) for certificate search results",
    )

    @property
    def keyfactor_tenant_id(self) -> str:
        return self.KEYFACTOR_TENANT_ID or self.AZURE_TENANT_ID

    @property
    def keyfactor_token_url(self) -> str:
        if self.KEYFACTOR_TOKEN_URL:
            return self.KEYFACTOR_TOKEN_URL
        return f"https://login.microsoftonline.com/{self.keyfactor_tenant_id}/oauth2/v2.0/token"

    # ── RBAC Roles ────────────────────────────────────────────────────
    ROLE_ADMIN: str = "OpsPortal.Admin"
    ROLE_WRITE: str = "OpsPortal.Write"
    ROLE_READ: str = "OpsPortal.Read"

    model_config = {
        "env_file": str(_BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


settings = Settings()  # type: ignore[call-arg]
