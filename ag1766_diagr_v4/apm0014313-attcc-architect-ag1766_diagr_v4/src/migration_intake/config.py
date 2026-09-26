"""
Application configuration.

This module provides typed, immutable configuration loaded from environment
variables. Configuration is validated at startup to fail fast on invalid
or insecure settings.

Safety gates:
- Shared/production environments reject implicit SQLite defaults
- LLM enablement requires HTTPS endpoint and complete credentials
- Actor ID must be a valid UUID
- Upload limits must be positive and within safety bounds
- Secrets are never logged or included in diagnostic responses

Usage:
    from migration_intake.config import Settings
    settings = Settings()  # Loads from environment
"""

from __future__ import annotations

import os
import re
from ipaddress import ip_address
from pathlib import Path  # noqa: TC003
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Maximum allowed upload size (500 MB) - safety ceiling
MAX_UPLOAD_CEILING_BYTES = 500 * 1024 * 1024

# Maximum allowed XLSX uncompressed size (1 GB) - ZIP bomb protection
MAX_XLSX_UNCOMPRESSED_CEILING_BYTES = 1024 * 1024 * 1024

# Maximum WaveUtil rows for synchronous processing
MAX_WAVEUTIL_ROWS_CEILING = 50_000


AppEnv = Literal["local", "test", "shared_test", "production"]
LLMProvider = Literal["mock", "openai_compatible", "anthropic", "bedrock"]
LLMAuthMode = Literal["bearer_token", "workload_identity", "none"]


class Settings(BaseSettings):
    def __init__(self, **values: object) -> None:
        # Disable .env loading only when explicitly requested (_env_file=None)
        # or when running under pytest — never for a plain Settings() call,
        # otherwise .env is never loaded and required fields fail validation.
        explicitly_disabled = "_env_file" in values and values["_env_file"] is None
        running_tests = (
            os.environ.get("APP_ENV") == "test"
            or os.environ.get("AWS_OUTPOST_APP_ENV") == "test"
        )
        if explicitly_disabled or ("_env_file" not in values and running_tests):
            values["_env_file"] = None
        super().__init__(**values)

    """
    Application settings loaded from environment variables.

    All settings are validated at construction time. Invalid or insecure
    configurations raise ValueError with a descriptive message.

    Attributes:
        app_env: Environment profile (local, test, shared_test, production)
        database_url: SQLAlchemy database URL
        evidence_root: Root directory for content-addressed evidence storage
        actor_id: Configured actor UUID for this slice
        actor_display_name: Human-readable actor name for audit/UI
        csrf_secret: Secret for signing CSRF tokens
        llm_provider: AI provider selection profile
        llm_enabled: Whether LLM network calls are permitted
        llm_outbound_enabled: Whether outbound LLM calls are permitted at runtime
        llm_base_url: OpenAI-compatible API base URL (HTTPS required)
        llm_model: Model identifier for LLM requests
        llm_api_token: Bearer token for LLM authentication
        max_upload_bytes: Maximum file upload size
        max_xlsx_uncompressed_bytes: Maximum XLSX expansion size
        max_waveutil_rows: Maximum WaveUtil rows for sync processing
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,  # Make settings immutable
        populate_by_name=True,
    )

    # Environment and database
    app_env: AppEnv = Field(
        default="local",
        validation_alias=AliasChoices("AWS_OUTPOST_APP_ENV", "APP_ENV"),
    )
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("AWS_OUTPOST_DATABASE_URL", "DATABASE_URL"),
    )
    oracle_client_lib_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_ORACLE_CLIENT_LIB_DIR", "ORACLE_CLIENT_LIB_DIR"
        ),
    )
    static_assets_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_STATIC_ASSETS_DIR", "STATIC_ASSETS_DIR"
        ),
    )
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_recycle_seconds: int = Field(default=3600, ge=60)
    sql_echo: bool = Field(default=False)

    # Evidence storage
    evidence_root: Path = Field(
        ...,
        validation_alias=AliasChoices("AWS_OUTPOST_EVIDENCE_ROOT", "EVIDENCE_ROOT"),
    )

    # Upload limits
    max_upload_bytes: int = Field(default=100 * 1024 * 1024)  # 100 MB default
    max_topology_base_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_MAX_TOPOLOGY_BASE_BYTES",
            "MAX_TOPOLOGY_BASE_BYTES",
        ),
    )
    max_xlsx_uncompressed_bytes: int = Field(default=500 * 1024 * 1024)  # 500 MB default
    max_waveutil_rows: int = Field(default=20_000)

    # Topology feature gate. The legacy generation path stays disabled until the
    # replacement immutable pipeline has passed its release gates.
    topology_generation_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_TOPOLOGY_GENERATION_ENABLED",
            "TOPOLOGY_GENERATION_ENABLED",
        ),
    )

    # Actor identity (configured for first slice)
    actor_id: str = Field(
        ...,
        validation_alias=AliasChoices("AWS_OUTPOST_ACTOR_ID", "ACTOR_ID"),
    )
    actor_display_name: str = Field(
        ...,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_ACTOR_DISPLAY_NAME", "ACTOR_DISPLAY_NAME"
        ),
    )
    actor_attuid: str | None = Field(default=None)

    # Security
    csrf_secret: SecretStr = Field(
        ...,
        validation_alias=AliasChoices("AWS_OUTPOST_CSRF_SECRET", "CSRF_SECRET"),
    )

    # Catalog
    catalog_path: Path | None = Field(default=None)
    workbook_contract_version: str = Field(default="APP_DATA_CAPTURE_V1")

    # AI/LLM configuration
    llm_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_ENABLED", "LLM_ENABLED"),
    )
    llm_provider: LLMProvider = Field(
        default="mock",
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_PROVIDER", "CANDIDATE_MAPPER_PROVIDER"),
    )
    llm_profile: str = Field(
        default="disabled",
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_PROFILE", "LLM_PROFILE"),
    )
    llm_outbound_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_OUTBOUND_ENABLED", "LLM_OUTBOUND_ENABLED"),
    )
    llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_BASE_URL", "LLM_BASE_URL"),
    )
    llm_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_MODEL", "LLM_MODEL"),
    )
    llm_auth_mode: LLMAuthMode = Field(
        default="bearer_token",
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_AUTH_MODE", "LLM_AUTH_MODE"),
    )
    llm_api_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_API_TOKEN", "LLM_API_TOKEN"),
    )
    llm_allowed_classifications_raw: str = Field(
        default="SYNTHETIC",
        validation_alias=AliasChoices(
            "AWS_OUTPOST_LLM_ALLOWED_CLASSIFICATIONS",
            "LLM_ALLOWED_CLASSIFICATIONS",
        ),
    )
    llm_connect_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_LLM_CONNECT_TIMEOUT_SECONDS",
            "LLM_CONNECT_TIMEOUT_SECONDS",
        ),
    )
    llm_read_timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=300,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_LLM_READ_TIMEOUT_SECONDS",
            "LLM_READ_TIMEOUT_SECONDS",
        ),
    )
    llm_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias=AliasChoices("AWS_OUTPOST_LLM_MAX_ATTEMPTS", "LLM_MAX_ATTEMPTS"),
    )
    llm_max_response_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_LLM_MAX_RESPONSE_BYTES",
            "LLM_MAX_RESPONSE_BYTES",
        ),
    )
    llm_max_fragment_chars: int = Field(
        default=12_000,
        ge=1_000,
        le=100_000,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_LLM_MAX_FRAGMENT_CHARS",
            "LLM_MAX_FRAGMENT_CHARS",
        ),
    )
    llm_max_requests_per_import: int = Field(
        default=20,
        ge=1,
        le=500,
        validation_alias=AliasChoices(
            "AWS_OUTPOST_LLM_MAX_REQUESTS_PER_IMPORT",
            "LLM_MAX_REQUESTS_PER_IMPORT",
        ),
    )

    # Logging
    log_level: str = Field(default="INFO")
    log_format: Literal["human", "json"] = Field(default="human")

    @field_validator("actor_id")
    @classmethod
    def validate_actor_id_is_uuid(cls, v: str) -> str:
        """Validate that actor_id is a valid UUID."""
        if not v:
            raise ValueError("AWS_OUTPOST_ACTOR_ID is required")
        try:
            UUID(v)
        except (ValueError, TypeError) as e:
            raise ValueError(f"AWS_OUTPOST_ACTOR_ID must be a valid UUID: {e}") from e
        return v

    @field_validator("max_upload_bytes")
    @classmethod
    def validate_upload_bytes(cls, v: int) -> int:
        """Validate upload limit is positive and within safety ceiling."""
        if v <= 0:
            raise ValueError("MAX_UPLOAD_BYTES must be positive")
        if v > MAX_UPLOAD_CEILING_BYTES:
            raise ValueError(
                f"MAX_UPLOAD_BYTES exceeds safety ceiling of {MAX_UPLOAD_CEILING_BYTES} bytes"
            )
        return v

    @field_validator("max_xlsx_uncompressed_bytes")
    @classmethod
    def validate_xlsx_bytes(cls, v: int) -> int:
        """Validate XLSX expansion limit is within safety ceiling."""
        if v <= 0:
            raise ValueError("MAX_XLSX_UNCOMPRESSED_BYTES must be positive")
        if v > MAX_XLSX_UNCOMPRESSED_CEILING_BYTES:
            raise ValueError(
                "MAX_XLSX_UNCOMPRESSED_BYTES exceeds safety ceiling"
            )
        return v

    @field_validator("max_waveutil_rows")
    @classmethod
    def validate_waveutil_rows(cls, v: int) -> int:
        """Validate WaveUtil row limit is within safety ceiling."""
        if v <= 0:
            raise ValueError("MAX_WAVEUTIL_ROWS must be positive")
        if v > MAX_WAVEUTIL_ROWS_CEILING:
            raise ValueError(
                f"MAX_WAVEUTIL_ROWS exceeds safety ceiling of {MAX_WAVEUTIL_ROWS_CEILING}"
            )
        return v

    @model_validator(mode="after")
    def validate_environment_constraints(self) -> Settings:
        """
        Validate cross-field constraints based on environment.

        - Shared/production environments require explicit AWS_OUTPOST_DATABASE_URL
        - Enabled LLM requires HTTPS endpoint and complete credentials
        """
        if self.app_env in ("shared_test", "production"):
            if not self.database_url:
                raise ValueError("AWS_OUTPOST_DATABASE_URL is required")
            if "sqlite" in self.database_url.lower():
                raise ValueError("AWS_OUTPOST_DATABASE_URL must point to Oracle")

        if self.llm_profile.strip() == "":
            raise ValueError("LLM_PROFILE must not be blank")

        # Validate provider/auth matrix and endpoint normalization.
        if self.llm_provider == "mock":
            if self.llm_outbound_enabled:
                raise ValueError("LLM_OUTBOUND_ENABLED cannot be true for provider=mock")
        elif self.llm_provider in ("openai_compatible", "anthropic"):
            if self.llm_auth_mode != "bearer_token":
                raise ValueError(
                    "LLM_AUTH_MODE must be bearer_token for openai_compatible/anthropic providers"
                )
        elif self.llm_provider == "bedrock":
            if self.llm_auth_mode != "workload_identity":
                raise ValueError(
                    "LLM_AUTH_MODE must be workload_identity for bedrock provider"
                )
            if self.llm_api_token:
                raise ValueError("LLM_API_TOKEN must not be configured for bedrock provider")

        # Validate LLM network profile when enabled and non-mock provider selected.
        if self.llm_enabled and self.llm_provider != "mock":
            if not self.llm_base_url:
                raise ValueError(
                    "LLM_BASE_URL is required when LLM is enabled for network providers"
                )
            if not self.llm_base_url.startswith("https://"):
                raise ValueError("HTTPS is required for LLM_BASE_URL when LLM is enabled")
            if self.llm_provider == "openai_compatible" and "/v1" in self.llm_base_url.rstrip("/"):
                raise ValueError(
                    "LLM_BASE_URL for openai_compatible must not include /v1; "
                    "the adapter appends endpoint paths"
                )
            if not self.llm_model:
                raise ValueError("LLM_MODEL is required when LLM is enabled for network providers")
            if self.llm_auth_mode == "bearer_token" and not self.llm_api_token:
                raise ValueError(
                    "LLM_API_TOKEN is required when LLM_AUTH_MODE is bearer_token"
                )

        return self

    @property
    def candidate_mapper_provider(self) -> LLMProvider:
        """Backward-compatible provider alias consumed by current mapper code."""
        return self.llm_provider

    @property
    def llm_allowed_classifications(self) -> tuple[str, ...]:
        """Parsed and normalized allowed classification policy."""
        raw = self.llm_allowed_classifications_raw.strip()
        if not raw:
            return ("SYNTHETIC",)
        values = tuple(
            token.strip().upper() for token in raw.split(",") if token.strip()
        )
        return values or ("SYNTHETIC",)

    @property
    def effective_database_url(self) -> str:
        """
        Return the configured database URL, with SQLite default for local/test.
        """
        if not self.database_url and self.app_env in ("local", "test"):
            return "sqlite:///./migration_intake.db"
        return self.database_url

    @property
    def database_classification(self) -> str:
        """
        Return a redacted database class for diagnostics.

        - LOOPBACK_NETWORK: network database on localhost/loopback
        - REMOTE_NETWORK: non-loopback network database
        """
        url = self.effective_database_url
        hostname = urlsplit(url).hostname
        if hostname is None:
            return "REMOTE_NETWORK"
        if hostname == "localhost":
            return "LOOPBACK_NETWORK"
        try:
            if ip_address(hostname).is_loopback:
                return "LOOPBACK_NETWORK"
        except ValueError:
            pass
        return "REMOTE_NETWORK"

    def redacted_database_url(self) -> str:
        """
        Get database URL with credentials redacted for logging.

        Removes userinfo (username:password) from the URL to prevent
        credential leakage in logs or diagnostics.
        """
        url = self.effective_database_url
        # Redact userinfo from URL (pattern: scheme://user:pass@host)
        return re.sub(r"://[^:]+:[^@]+@", "://***:***@", url)
