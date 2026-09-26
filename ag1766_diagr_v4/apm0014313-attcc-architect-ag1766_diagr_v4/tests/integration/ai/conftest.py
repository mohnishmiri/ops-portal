"""
Pytest configuration for AI integration tests.

Sets NO_PROXY to bypass corporate proxies for localhost connections,
which is required for the fake HTTP server tests to work correctly.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def bypass_proxy_for_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure localhost connections bypass any configured HTTP proxy.

    Corporate environments often have HTTP_PROXY/HTTPS_PROXY set, which
    causes requests to 127.0.0.1 to be routed through the proxy. The proxy
    then rejects them with "Request on loopback from external IP".

    This fixture sets NO_PROXY to include localhost addresses, ensuring
    the fake HTTP server tests work correctly.
    """
    # Get existing NO_PROXY value and append localhost if not already present
    existing = os.environ.get("NO_PROXY", "")
    localhost_entries = "127.0.0.1,localhost,::1"

    if existing:
        # Check if localhost entries are already present
        existing_lower = existing.lower()
        if "127.0.0.1" not in existing_lower:
            new_value = f"{existing},{localhost_entries}"
        else:
            new_value = existing
    else:
        new_value = localhost_entries

    monkeypatch.setenv("NO_PROXY", new_value)
    monkeypatch.setenv("no_proxy", new_value)  # Some libraries check lowercase
