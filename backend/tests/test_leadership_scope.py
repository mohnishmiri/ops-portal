"""Tests for scope-aware leadership dashboard helpers."""

from app.schemas.cost import LEADERSHIP_SCHEMA_VERSION
from app.services.leadership_sync_service import (
    LEADERSHIP_DASHBOARD_CACHE_KEY,
    is_current_leadership_payload,
    leadership_dashboard_cache_key,
    leadership_snapshot_scope_key,
)


def test_leadership_cache_key_all_for_full_scope() -> None:
    assert leadership_dashboard_cache_key(None) == LEADERSHIP_DASHBOARD_CACHE_KEY
    assert leadership_dashboard_cache_key([]) == LEADERSHIP_DASHBOARD_CACHE_KEY


def test_leadership_cache_key_differs_per_scope() -> None:
    key_a = leadership_dashboard_cache_key(["sub-a"])
    key_b = leadership_dashboard_cache_key(["sub-b"])
    key_ab = leadership_dashboard_cache_key(["sub-a", "sub-b"])
    assert key_a != key_b
    assert key_a != key_ab
    assert key_a.startswith(f"pagecache:leadership:v{LEADERSHIP_SCHEMA_VERSION}:dashboard:")


def test_leadership_cache_keys_are_versioned() -> None:
    # A payload cached by an older release (different KPIs) must never be read back.
    assert LEADERSHIP_DASHBOARD_CACHE_KEY != "pagecache:leadership:dashboard:all"
    assert f":v{LEADERSHIP_SCHEMA_VERSION}:" in LEADERSHIP_DASHBOARD_CACHE_KEY


def test_payload_without_current_schema_version_is_outdated() -> None:
    assert is_current_leadership_payload({}) is False
    assert is_current_leadership_payload({"schema_version": 1}) is False
    assert is_current_leadership_payload({"schema_version": LEADERSHIP_SCHEMA_VERSION}) is True


def test_leadership_snapshot_scope_key() -> None:
    assert leadership_snapshot_scope_key(None) == "ALL"
    assert leadership_snapshot_scope_key([]) == "ALL"
    scoped = leadership_snapshot_scope_key(["sub-a", "sub-b"])
    assert scoped.startswith("scope:")
    assert leadership_snapshot_scope_key(["sub-b", "sub-a"]) == scoped
