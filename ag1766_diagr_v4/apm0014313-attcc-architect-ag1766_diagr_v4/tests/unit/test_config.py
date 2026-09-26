"""
Tests for application configuration.

These tests verify:
- Valid local settings produce SQLite configuration and mock AI
- Shared/production settings reject implicit SQLite
- Enabled LLM rejects HTTP or incomplete configuration
- Invalid actor UUID/upload limits fail startup
- Configuration is immutable after creation

TDD: Write these tests FIRST, then implement config.py to make them pass.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the developer environment from overriding isolated test inputs."""
    names = (
        "APP_ENV",
        "DATABASE_URL",
        "EVIDENCE_ROOT",
        "ACTOR_ID",
        "ACTOR_DISPLAY_NAME",
        "CSRF_SECRET",
        "ORACLE_CLIENT_LIB_DIR",
        "LLM_ENABLED",
        "LLM_PROVIDER",
        "LLM_PROFILE",
        "LLM_OUTBOUND_ENABLED",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_AUTH_MODE",
        "LLM_API_TOKEN",
        "LLM_ALLOWED_CLASSIFICATIONS",
        "LLM_CONNECT_TIMEOUT_SECONDS",
        "LLM_READ_TIMEOUT_SECONDS",
        "LLM_MAX_ATTEMPTS",
        "LLM_MAX_RESPONSE_BYTES",
        "LLM_MAX_FRAGMENT_CHARS",
        "LLM_MAX_REQUESTS_PER_IMPORT",
    )
    for name in names:
        monkeypatch.delenv(f"AWS_OUTPOST_{name}", raising=False)


def test_prefixed_environment_names_load_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    actor_id = str(uuid.uuid4())

    monkeypatch.setenv("AWS_OUTPOST_APP_ENV", "local")
    monkeypatch.setenv("AWS_OUTPOST_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("AWS_OUTPOST_EVIDENCE_ROOT", str(evidence_root))
    monkeypatch.setenv("AWS_OUTPOST_ACTOR_ID", actor_id)
    monkeypatch.setenv("AWS_OUTPOST_ACTOR_DISPLAY_NAME", "AWS Outpost Test")
    monkeypatch.setenv("AWS_OUTPOST_CSRF_SECRET", "test-secret-at-least-32-characters-long")

    from migration_intake.config import Settings

    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.database_url == "sqlite:///:memory:"
    assert settings.evidence_root == evidence_root
    assert settings.actor_id == actor_id
    assert settings.actor_display_name == "AWS Outpost Test"


class TestLocalConfiguration:
    """Tests for local development configuration."""

    def test_valid_local_settings_produce_sqlite_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Valid local settings should produce SQLite database configuration."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")

        from migration_intake.config import Settings

        settings = Settings(_env_file=None)

        assert settings.app_env == "local"
        # Use effective_database_url which provides the default for local env
        assert "sqlite" in settings.effective_database_url.lower()
        assert settings.candidate_mapper_provider == "mock"
        assert settings.llm_enabled is False

    def test_local_settings_default_to_mock_ai(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Local settings should default to mock AI provider."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")

        from migration_intake.config import Settings

        settings = Settings(_env_file=None)

        assert settings.candidate_mapper_provider == "mock"
        assert settings.llm_enabled is False


class TestProductionConfiguration:
    """Tests for shared/production configuration safety."""

    def test_shared_env_rejects_implicit_sqlite(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Shared environment must not fall back to implicit SQLite."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "shared_test")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        # Deliberately NOT setting DATABASE_URL

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="DATABASE_URL.*required"):
            Settings(_env_file=None)

    def test_production_env_rejects_implicit_sqlite(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Production environment must not fall back to implicit SQLite."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        # Deliberately NOT setting DATABASE_URL

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="DATABASE_URL.*required"):
            Settings(_env_file=None)

class TestLocalRemoteDatabaseContainment:
    """Local mode accepts the configured remote Oracle database."""

    def test_local_mode_accepts_remote_database_without_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()
        remote_url = "oracle+oracledb://user:pw@db.example.com:1521/perf"

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("DATABASE_URL", remote_url)
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")

        from migration_intake.config import Settings

        settings = Settings(_env_file=None)
        assert settings.database_classification == "REMOTE_NETWORK"

    def test_local_mode_accepts_loopback_database_without_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("DATABASE_URL", "oracle+oracledb://user:pw@127.0.0.1:1521/freepdb1")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")

        from migration_intake.config import Settings

        settings = Settings(_env_file=None)
        assert settings.database_classification == "LOOPBACK_NETWORK"


class TestLLMConfiguration:
    """Tests for LLM/AI configuration safety."""

    def test_enabled_llm_rejects_http_endpoint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Enabled LLM must reject HTTP (non-HTTPS) endpoints."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("LLM_BASE_URL", "http://insecure-endpoint.example.com")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        monkeypatch.setenv("LLM_API_TOKEN", "test-token")

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="HTTPS.*required"):
            Settings(_env_file=None)

    def test_enabled_llm_rejects_missing_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Enabled LLM must have API token configured."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        # Deliberately NOT setting LLM_API_TOKEN

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="LLM_API_TOKEN.*required"):
            Settings(_env_file=None)

    def test_enabled_llm_rejects_missing_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Enabled LLM must have model configured."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("LLM_API_TOKEN", "test-token")
        # Deliberately NOT setting LLM_MODEL

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="LLM_MODEL.*required"):
            Settings(_env_file=None)

    def test_openai_base_url_rejects_embedded_v1_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """OpenAI-compatible base URL must be an origin/base path without /v1."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.internal/v1")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        monkeypatch.setenv("LLM_API_TOKEN", "test-token")

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="must not include /v1"):
            Settings(_env_file=None)

    def test_bedrock_rejects_bearer_token_auth_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Bedrock must use workload identity, never bearer token mode."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        monkeypatch.setenv("LLM_AUTH_MODE", "bearer_token")
        monkeypatch.setenv("LLM_BASE_URL", "https://bedrock-runtime.us-east-1.amazonaws.com")
        monkeypatch.setenv("LLM_MODEL", "anthropic.claude-v2")
        monkeypatch.setenv("LLM_API_TOKEN", "must-not-be-used")

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="workload_identity"):
            Settings(_env_file=None)

    def test_mock_provider_rejects_outbound_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Mock provider cannot enable outbound network mode."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        monkeypatch.setenv("LLM_OUTBOUND_ENABLED", "true")

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="cannot be true for provider=mock"):
            Settings(_env_file=None)

    def test_allowed_classifications_are_normalized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Classification policy parsing is deterministic and uppercase."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("LLM_ALLOWED_CLASSIFICATIONS", "synthetic, redacted")

        from migration_intake.config import Settings

        settings = Settings(_env_file=None)
        assert settings.llm_allowed_classifications == ("SYNTHETIC", "REDACTED")


class TestActorConfiguration:
    """Tests for actor identity configuration."""

    def test_invalid_actor_uuid_fails_startup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Malformed actor UUID must fail at startup."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", "not-a-valid-uuid")
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="ACTOR_ID.*UUID"):
            Settings(_env_file=None)

    def test_missing_actor_id_fails_startup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Missing actor ID must fail at startup."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")

        # Override ACTOR_ID with empty string to ensure it's missing
        # (pydantic-settings reads from .env file, so we must explicitly override)
        monkeypatch.setenv("ACTOR_ID", "")

        from migration_intake.config import Settings

        # Pydantic raises ValidationError for missing required fields
        with pytest.raises((ValueError, ValidationError), match="actor_id|ACTOR_ID"):
            Settings(_env_file=None)


class TestUploadLimits:
    """Tests for upload limit configuration."""

    def test_zero_upload_limit_fails_startup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Zero upload limit must fail at startup."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "0")

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="MAX_UPLOAD_BYTES.*positive"):
            Settings(_env_file=None)

    def test_excessive_upload_limit_fails_startup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Excessively large upload limit must fail at startup."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        # 10 GB - way too large
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "10737418240")

        from migration_intake.config import Settings

        with pytest.raises(ValueError, match="MAX_UPLOAD_BYTES.*exceeds"):
            Settings(_env_file=None)

    def test_valid_upload_limits_accepted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Valid upload limits should be accepted."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "52428800")  # 50 MB

        from migration_intake.config import Settings

        settings = Settings(_env_file=None)

        assert settings.max_upload_bytes == 52428800


class TestConfigurationImmutability:
    """Tests for configuration immutability."""

    def test_settings_are_immutable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Settings should be immutable after creation."""
        evidence_root = tmp_path / "evidence"
        evidence_root.mkdir()

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("EVIDENCE_ROOT", str(evidence_root))
        monkeypatch.setenv("ACTOR_ID", str(uuid.uuid4()))
        monkeypatch.setenv("ACTOR_DISPLAY_NAME", "Test User")
        monkeypatch.setenv("CSRF_SECRET", "test-secret-at-least-32-characters-long")

        from migration_intake.config import Settings

        settings = Settings(_env_file=None)

        with pytest.raises((TypeError, ValueError)):
            settings.app_env = "production"  # type: ignore[misc]
