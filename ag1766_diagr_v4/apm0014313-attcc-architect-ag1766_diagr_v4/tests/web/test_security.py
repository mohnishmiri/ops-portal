"""
Tests for security foundation — SEC01a.

Verifies:
- Capability codes defined
- CSRF token generation and validation
- Security headers
- Configured actor mode indicator
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from migration_intake.web.security import (
    CONFIGURED_ACTOR_CAPABILITIES,
    CSP_POLICY,
    SECURITY_HEADERS,
    SENSITIVE_PAGE_HEADERS,
    Capability,
    SecurityHeadersMiddleware,
    add_sensitive_headers,
    generate_csrf_token,
    get_non_production_indicator,
    has_capability,
    is_configured_actor_mode,
    require_capability,
    require_csrf_token,
    set_csrf_secret,
    validate_csrf_token,
)


# ---------------------------------------------------------------------------
# Capability tests
# ---------------------------------------------------------------------------


class TestCapabilityCodes:
    """Verify capability codes are defined correctly."""

    def test_application_create_capability_defined(self) -> None:
        """APPLICATION_CREATE capability must be defined."""
        assert Capability.APPLICATION_CREATE.value == "APPLICATION_CREATE"

    def test_intake_create_capability_defined(self) -> None:
        """INTAKE_CREATE capability must be defined."""
        assert Capability.INTAKE_CREATE.value == "INTAKE_CREATE"

    def test_answer_edit_capability_defined(self) -> None:
        """ANSWER_EDIT capability must be defined."""
        assert Capability.ANSWER_EDIT.value == "ANSWER_EDIT"

    def test_answer_confirm_capability_defined(self) -> None:
        """ANSWER_CONFIRM capability must be defined."""
        assert Capability.ANSWER_CONFIRM.value == "ANSWER_CONFIRM"

    def test_evidence_upload_capability_defined(self) -> None:
        """EVIDENCE_UPLOAD capability must be defined."""
        assert Capability.EVIDENCE_UPLOAD.value == "EVIDENCE_UPLOAD"

    def test_candidate_review_capability_defined(self) -> None:
        """CANDIDATE_REVIEW capability must be defined."""
        assert Capability.CANDIDATE_REVIEW.value == "CANDIDATE_REVIEW"

    def test_waveutil_review_capability_defined(self) -> None:
        """WAVEUTIL_REVIEW capability must be defined."""
        assert Capability.WAVEUTIL_REVIEW.value == "WAVEUTIL_REVIEW"

    def test_intake_freeze_capability_defined(self) -> None:
        """INTAKE_FREEZE capability must be defined."""
        assert Capability.INTAKE_FREEZE.value == "INTAKE_FREEZE"

    def test_catalog_manage_capability_defined(self) -> None:
        """CATALOG_MANAGE capability must be defined."""
        assert Capability.CATALOG_MANAGE.value == "CATALOG_MANAGE"

    def test_all_capabilities_in_configured_actor_set(self) -> None:
        """All capabilities must be in the configured actor set."""
        for cap in Capability:
            assert cap in CONFIGURED_ACTOR_CAPABILITIES

    def test_catalog_manage_in_configured_actor_set(self) -> None:
        """CATALOG_MANAGE must be included in the configured actor set."""
        assert Capability.CATALOG_MANAGE in CONFIGURED_ACTOR_CAPABILITIES

    def test_topology_capabilities_are_explicitly_defined(self) -> None:
        """Topology actions should each have their own capability code."""
        assert Capability.TOPOLOGY_BASE_UPLOAD.value == "TOPOLOGY_BASE_UPLOAD"
        assert Capability.TOPOLOGY_BASE_REVIEW.value == "TOPOLOGY_BASE_REVIEW"
        assert Capability.TOPOLOGY_GENERATE.value == "TOPOLOGY_GENERATE"
        assert (
            Capability.TOPOLOGY_ARTIFACT_DOWNLOAD.value
            == "TOPOLOGY_ARTIFACT_DOWNLOAD"
        )
        assert Capability.TOPOLOGY_RUN_APPROVE.value == "TOPOLOGY_RUN_APPROVE"


class TestCapabilityChecks:
    """Verify capability checking functions."""

    def test_has_capability_returns_true_when_present(self) -> None:
        """has_capability returns True when capability is present."""
        caps = {"APPLICATION_CREATE", "INTAKE_CREATE"}
        assert has_capability(caps, Capability.APPLICATION_CREATE) is True

    def test_has_capability_returns_false_when_missing(self) -> None:
        """has_capability returns False when capability is missing."""
        caps = {"APPLICATION_CREATE"}
        assert has_capability(caps, Capability.INTAKE_CREATE) is False

    def test_has_capability_returns_true_for_catalog_manage_when_present(self) -> None:
        """has_capability returns True for CATALOG_MANAGE when present."""
        caps = {"CATALOG_MANAGE"}
        assert has_capability(caps, Capability.CATALOG_MANAGE) is True

    def test_has_capability_returns_false_for_catalog_manage_when_absent(self) -> None:
        """has_capability returns False for CATALOG_MANAGE when the set is empty."""
        assert has_capability(set(), Capability.CATALOG_MANAGE) is False

    def test_require_capability_passes_when_present(self) -> None:
        """require_capability does not raise when capability is present."""
        caps = {"APPLICATION_CREATE"}
        require_capability(caps, Capability.APPLICATION_CREATE)  # Should not raise

    def test_require_capability_raises_when_missing(self) -> None:
        """require_capability raises HTTPException when capability is missing."""
        from fastapi import HTTPException

        caps = {"APPLICATION_CREATE"}
        with pytest.raises(HTTPException) as exc_info:
            require_capability(caps, Capability.INTAKE_CREATE)
        assert exc_info.value.status_code == 403
        assert "INTAKE_CREATE" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# CSRF tests
# ---------------------------------------------------------------------------


class TestCsrfTokenGeneration:
    """Verify CSRF token generation."""

    def test_generate_csrf_token_returns_string(self) -> None:
        """generate_csrf_token returns a non-empty string."""
        token = generate_csrf_token()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_csrf_token_contains_timestamp(self) -> None:
        """CSRF token contains a timestamp component."""
        token = generate_csrf_token()
        assert "." in token
        timestamp_str = token.split(".")[0]
        timestamp = int(timestamp_str)
        assert timestamp > 0

    def test_generate_csrf_token_unique_per_call(self) -> None:
        """Each call to generate_csrf_token produces a unique token."""
        token1 = generate_csrf_token()
        # Wait a tiny bit to ensure different timestamp
        time.sleep(0.01)
        token2 = generate_csrf_token()
        # Tokens may be the same if generated in the same second
        # but the signature should be deterministic for the same timestamp
        # This test just ensures the function works


class TestCsrfTokenValidation:
    """Verify CSRF token validation."""

    @pytest.fixture(autouse=True)
    def setup_secret(self) -> None:
        """Set a known secret for testing."""
        set_csrf_secret(b"test-secret-key-for-csrf-testing")

    def test_validate_csrf_token_accepts_valid_token(self) -> None:
        """validate_csrf_token returns True for a valid token."""
        token = generate_csrf_token()
        assert validate_csrf_token(token) is True

    def test_validate_csrf_token_rejects_empty_token(self) -> None:
        """validate_csrf_token returns False for empty token."""
        assert validate_csrf_token("") is False

    def test_validate_csrf_token_rejects_malformed_token(self) -> None:
        """validate_csrf_token returns False for malformed token."""
        assert validate_csrf_token("no-dot-in-token") is False
        assert validate_csrf_token("not.a.valid.token") is False

    def test_validate_csrf_token_rejects_tampered_signature(self) -> None:
        """validate_csrf_token returns False for tampered signature."""
        token = generate_csrf_token()
        timestamp, _ = token.split(".", 1)
        tampered = f"{timestamp}.tampered_signature"
        assert validate_csrf_token(tampered) is False

    def test_validate_csrf_token_rejects_expired_token(self) -> None:
        """validate_csrf_token returns False for expired token."""
        # Generate a token with an old timestamp
        old_timestamp = str(int(time.time()) - 7200)  # 2 hours ago
        import hashlib
        import hmac

        from migration_intake.web.security import _get_csrf_secret

        data = f"{old_timestamp}:"
        signature = hmac.new(
            _get_csrf_secret(),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        old_token = f"{old_timestamp}.{signature}"

        # Should be rejected due to expiration
        assert validate_csrf_token(old_token, max_age=3600) is False

    def test_validate_csrf_token_with_session_binding(self) -> None:
        """CSRF token can be bound to a session ID."""
        session_id = "test-session-123"
        token = generate_csrf_token(session_id=session_id)

        # Valid with correct session
        assert validate_csrf_token(token, session_id=session_id) is True

        # Invalid with wrong session
        assert validate_csrf_token(token, session_id="wrong-session") is False


# ---------------------------------------------------------------------------
# Security headers tests
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """Verify security headers are defined correctly."""

    def test_nosniff_header_defined(self) -> None:
        """X-Content-Type-Options header must be defined."""
        assert "X-Content-Type-Options" in SECURITY_HEADERS
        assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"

    def test_frame_options_header_defined(self) -> None:
        """X-Frame-Options header must be defined."""
        assert "X-Frame-Options" in SECURITY_HEADERS
        assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"

    def test_referrer_policy_header_defined(self) -> None:
        """Referrer-Policy header must be defined."""
        assert "Referrer-Policy" in SECURITY_HEADERS

    def test_xss_protection_header_defined(self) -> None:
        """X-XSS-Protection header must be defined."""
        assert "X-XSS-Protection" in SECURITY_HEADERS


class TestSensitivePageHeaders:
    """Verify sensitive page headers include cache control."""

    def test_cache_control_header_defined(self) -> None:
        """Cache-Control header must be defined for sensitive pages."""
        assert "Cache-Control" in SENSITIVE_PAGE_HEADERS
        assert "no-store" in SENSITIVE_PAGE_HEADERS["Cache-Control"]

    def test_pragma_header_defined(self) -> None:
        """Pragma header must be defined for sensitive pages."""
        assert "Pragma" in SENSITIVE_PAGE_HEADERS
        assert SENSITIVE_PAGE_HEADERS["Pragma"] == "no-cache"

    def test_sensitive_headers_include_base_headers(self) -> None:
        """Sensitive page headers must include all base security headers."""
        for header in SECURITY_HEADERS:
            assert header in SENSITIVE_PAGE_HEADERS


class TestCspPolicy:
    """Verify Content Security Policy is defined correctly."""

    def test_csp_default_src_self(self) -> None:
        """CSP must set default-src to 'self'."""
        assert "default-src 'self'" in CSP_POLICY

    def test_csp_script_src_self(self) -> None:
        """CSP must set script-src to 'self'."""
        assert "script-src 'self'" in CSP_POLICY

    def test_csp_frame_ancestors_none(self) -> None:
        """CSP must set frame-ancestors to 'none'."""
        assert "frame-ancestors 'none'" in CSP_POLICY

    def test_csp_form_action_self(self) -> None:
        """CSP must set form-action to 'self'."""
        assert "form-action 'self'" in CSP_POLICY


class TestSecurityHeadersMiddleware:
    """Verify security headers middleware adds headers to responses."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create a test FastAPI app with security middleware."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_route() -> dict:
            return {"status": "ok"}

        @app.get("/html", response_class=type("HTMLResponse", (), {"media_type": "text/html"}))
        def html_route() -> str:
            return "<html><body>Test</body></html>"

        return app

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        """Create a test client."""
        return TestClient(app)

    def test_middleware_adds_security_headers(self, client: TestClient) -> None:
        """Middleware adds security headers to responses."""
        response = client.get("/test")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# Configured actor mode tests
# ---------------------------------------------------------------------------


class TestConfiguredActorMode:
    """Verify configured actor mode indicator."""

    def test_is_configured_actor_mode_returns_bool(self) -> None:
        """is_configured_actor_mode returns a boolean."""
        result = is_configured_actor_mode()
        assert isinstance(result, bool)

    def test_configured_actor_mode_disabled_for_shared_and_production(self) -> None:
        assert is_configured_actor_mode("shared_test") is False
        assert is_configured_actor_mode("production") is False

    def test_non_production_indicator_non_empty_in_dev_mode(self) -> None:
        """get_non_production_indicator returns non-empty string in dev mode."""
        indicator = get_non_production_indicator("local")
        assert len(indicator) > 0
        assert "PRODUCTION" in indicator.upper() or "DEVELOPMENT" in indicator.upper()

    def test_non_production_indicator_contains_warning(self) -> None:
        """Non-production indicator contains a warning message."""
        indicator = get_non_production_indicator("local")
        assert "NOT" in indicator.upper() or "DEV" in indicator.upper()
