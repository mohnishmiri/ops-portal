"""
Application configuration via Pydantic Settings.

All sensitive values are loaded from environment variables or Azure Key Vault.
Never hardcode secrets in this file.
"""

import tomllib
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _project_version() -> str:
    """Version from backend/pyproject.toml, the file bump_version.sh treats as canonical.

    A literal here drifted (the API said 1.3.0 while the UI footer said 1.3.11)
    because the bump script doesn't edit this file.
    """
    try:
        with (_BACKEND_DIR / "pyproject.toml").open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Application ───────────────────────────────────────────────────
    # An APP_VERSION environment variable still overrides this.
    APP_VERSION: str = Field(default_factory=_project_version)
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
    # Base URL for links in emails (access requests, alerts, certificate
    # reports).  Was read with getattr() but never declared, so every link
    # pointed at the local dev server.
    PORTAL_BASE_URL: str = Field(default="http://localhost:5177", description="Public URL of the portal UI")

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
    KEYFACTOR_CA_BUNDLE: str = Field(
        default="",
        description=(
            "Optional PEM CA file trusted in addition to the default bundle, e.g. the corporate root "
            "CA when a TLS-inspecting proxy sits between the portal and Keyfactor"
        ),
    )
    KEYFACTOR_DEFAULT_CA: str = Field(
        default="",
        description="Optional default issuing CA (logical name) used to pre-fill enrollment",
    )
    KEYFACTOR_DEFAULT_TEMPLATE: str = Field(
        default="",
        description="Optional default certificate template short name used to pre-fill enrollment",
    )
    KEYFACTOR_ENROLLMENT_PATTERNS: str = Field(
        default="",
        description=(
            "Enrollment patterns offered when the service account cannot list them, as comma-separated "
            "'id:name|template' entries, e.g. '28:Digicert-Standard-SHA2-4096Key|Digicert-Standard-SHA2-4096Key'. "
            "The template short name links the pattern to its key and CA policy."
        ),
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

    # ── Certificate private-key escrow ────────────────────────────────
    # Keyfactor hands over a PFX only at the moment of issuance, so without
    # escrow a certificate can be loaded into exactly one Key Vault and never
    # again. When escrow is enabled the portal stores that one-time PFX as a
    # secret in a dedicated Key Vault — never in PostgreSQL — so the same
    # certificate and key can be imported into any number of vaults later.
    CERT_KEY_ESCROW_ENABLED: bool = Field(
        default=False,
        description="Capture issuance-time PFX material into the escrow Key Vault for later AKV loads",
    )
    CERT_KEY_ESCROW_VAULT: str = Field(
        default="",
        description="Name of the dedicated escrow Key Vault, e.g. opsportal-cert-escrow-kv",
    )
    CERT_KEY_ESCROW_VAULT_URI: str = Field(
        default="",
        description="Optional full escrow vault URI; overrides CERT_KEY_ESCROW_VAULT (sovereign clouds)",
    )

    @property
    def cert_key_escrow_vault_uri(self) -> str:
        """Normalized escrow vault URI (trailing slash), or "" when unconfigured."""
        if self.CERT_KEY_ESCROW_VAULT_URI.strip():
            uri = self.CERT_KEY_ESCROW_VAULT_URI.strip()
        elif self.CERT_KEY_ESCROW_VAULT.strip():
            uri = f"https://{self.CERT_KEY_ESCROW_VAULT.strip()}.vault.azure.net"
        else:
            return ""
        return uri if uri.endswith("/") else f"{uri}/"

    @property
    def cert_key_escrow_active(self) -> bool:
        """Escrow only runs when explicitly enabled *and* pointed at a vault."""
        return bool(self.CERT_KEY_ESCROW_ENABLED and self.cert_key_escrow_vault_uri)

    # ── Credential checks (Tools module) ──────────────────────────────
    # Endpoints the portal binds against to answer "does this password or
    # token still work?".  Each is overridable because the paths below are
    # the documented ones, not ones this portal has verified in your tenant.
    CRED_CHECK_TIMEOUT_SECONDS: int = Field(
        default=15,
        description="Timeout in seconds for a single credential check",
    )
    CRED_CHECK_CA_BUNDLE: str = Field(
        default="",
        description="Optional PEM CA file trusted in addition to the default bundle (TLS-inspecting proxy)",
    )
    CRED_CHECK_LDAP_ITSERVICES: str = Field(
        default="",
        description="LDAPS URL of the ITSERVICES domain controller, e.g. ldaps://dc.itservices.example.com:636",
    )
    CRED_CHECK_LDAP_TESTITSERVICES: str = Field(
        default="",
        description="LDAPS URL of the TESTITSERVICES domain controller",
    )
    # Read-only directory reader, used to fill in an inventory account's
    # details without anyone typing that account's own password.  It reads
    # account attributes (name, password expiry, last sign-in, failed
    # sign-ins) and nothing else: no password is read, and nothing is
    # written.  Blank = the inventory simply waits to be told by a check.
    CRED_CHECK_LDAP_READER_ITSERVICES: str = Field(
        default="",
        description=(
            "Read-only bind account for ITSERVICES: a plain username, DOMAIN\\name, a UPN or a DN. "
            "A plain username is qualified with the domain before binding."
        ),
    )
    CRED_CHECK_LDAP_READER_PASSWORD_ITSERVICES: str = Field(
        default="",
        description="Password for CRED_CHECK_LDAP_READER_ITSERVICES",
    )
    CRED_CHECK_LDAP_READER_TESTITSERVICES: str = Field(
        default="",
        description="Read-only bind account for TESTITSERVICES",
    )
    CRED_CHECK_LDAP_READER_PASSWORD_TESTITSERVICES: str = Field(
        default="",
        description="Password for CRED_CHECK_LDAP_READER_TESTITSERVICES",
    )
    CRED_CHECK_JFROG_URL: str = Field(
        default="https://artifact.it.att.com",
        description="Base URL of the JFrog Artifactory Bronze instance",
    )
    CRED_CHECK_JFROG_URL_GOLD: str = Field(
        default="https://artifact-gold.it.att.com",
        description="Base URL of the JFrog Artifactory Gold instance",
    )
    CRED_CHECK_AAF_URL_PROD: str = Field(
        default="https://aaf-azure.it.att.com",
        description="Base URL of the production AAF instance",
    )
    CRED_CHECK_AAF_URL_NONPROD: str = Field(
        default="https://aafist-azure.it.att.com",
        description="Base URL of the non-production (IST) AAF instance",
    )
    CRED_CHECK_AAF_PATH: str = Field(
        default="/authn/basicAuth",
        description="AAF path that answers 200 for a valid basic-auth credential",
    )
    CRED_CHECK_AAF_CREDS_PATH: str = Field(
        default="/authn/creds/id/{id}",
        description="AAF path listing an identity's credentials and their expiry; {id} is the identity",
    )

    # ── MongoDB Atlas ─────────────────────────────────────────────────
    # A programmatic API key (HTTP Digest). Every Atlas call the portal makes
    # runs as this key, so give it only the roles the module needs — Project
    # Cluster Manager for start/stop and tier changes, Project Owner for
    # database users and the IP access list — on the projects it should see.
    # When the organization requires an IP access list for the Admin API, the
    # portal's egress IP must be on the key's API access list.
    MONGODB_ATLAS_BASE_URL: str = Field(
        default="https://cloud.mongodb.com",
        description="Atlas host; the Admin API v2 is served under /api/atlas/v2",
    )
    MONGODB_ATLAS_PUBLIC_KEY: str = Field(default="", description="Atlas API key public key")
    MONGODB_ATLAS_PRIVATE_KEY: str = Field(default="", description="Atlas API key private key (Key Vault)")
    MONGODB_ATLAS_ORG_ID: str = Field(
        default="",
        description="Optional: only show projects of this Atlas organization",
    )
    MONGODB_ATLAS_PROJECT_IDS: str = Field(
        default="",
        description=(
            "Optional comma-separated Atlas project IDs. When set, the portal shows and acts on these "
            "projects only, even if the API key can see more."
        ),
    )
    MONGODB_ATLAS_TIMEOUT_SECONDS: int = Field(default=30, description="Timeout for one Atlas API call")
    MONGODB_ATLAS_CA_BUNDLE: str = Field(
        default="",
        description="Optional PEM CA file trusted in addition to the default bundle (TLS-inspecting proxy)",
    )
    MONGODB_ATLAS_OPERATION_TIMEOUT_MINUTES: int = Field(
        default=60,
        description="How long a stop/start may take before the portal reports it as failed",
    )

    @property
    def mongodb_atlas_configured(self) -> bool:
        return bool(self.MONGODB_ATLAS_PUBLIC_KEY.strip() and self.MONGODB_ATLAS_PRIVATE_KEY.strip())

    @property
    def mongodb_atlas_project_allowlist(self) -> frozenset[str]:
        return frozenset(p.strip() for p in self.MONGODB_ATLAS_PROJECT_IDS.split(",") if p.strip())

    # ── RBAC Roles ────────────────────────────────────────────────────
    # Super Admin manages every project. It is deliberately an Entra app role
    # only — nothing in the portal can grant it.
    ROLE_SUPER_ADMIN: str = "OpsPortal.SuperAdmin"
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
