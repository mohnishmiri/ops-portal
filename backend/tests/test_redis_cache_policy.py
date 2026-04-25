"""Tests for the DB-backed cache manager toggle behaviour."""

from app.core import db_cache


def test_cache_enabled_for_key_allows_all_when_enabled() -> None:
    """When cache is enabled (default), all keys are allowed."""
    db_cache._cache_admin_enabled = True
    assert db_cache.is_cache_enabled_for_key("pagecache:leadership:dashboard:all") is True
    assert db_cache.is_cache_enabled_for_key("pagecache:amortized:summary:PROD:6") is True
    assert db_cache.is_cache_enabled_for_key("cost:query:any") is True


def test_cache_disabled_blocks_pagecache_keys() -> None:
    """When cache is disabled via admin toggle, pagecache: keys are blocked."""
    db_cache._cache_admin_enabled = False
    assert db_cache.is_cache_enabled_for_key("pagecache:leadership:dashboard:all") is False
    assert db_cache.is_cache_enabled_for_key("pagecache:amortized:summary:PROD:6") is False
    # Non-pagecache keys still allowed
    assert db_cache.is_cache_enabled_for_key("cost:query:any") is True
    db_cache._cache_admin_enabled = True
