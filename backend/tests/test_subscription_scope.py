"""Tests for per-request subscription scope resolution."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.subscription_scope import (
    get_scoped_subscription_ids,
    reset_scoped_subscription_ids,
    resolve_effective_subscription_ids,
    set_scoped_subscription_ids,
    subscription_ids_for_manual_amortized_sync,
)


@pytest.mark.anyio
async def test_resolve_effective_returns_monitored_when_no_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a", "sub-b"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    result = await resolve_effective_subscription_ids()
    assert result == ["sub-a", "sub-b"]


@pytest.mark.anyio
async def test_resolve_effective_intersects_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a", "sub-b", "sub-c"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    result = await resolve_effective_subscription_ids(
        selected_subscription_ids=["sub-b", "sub-c"],
    )
    assert result == ["sub-b", "sub-c"]


@pytest.mark.anyio
async def test_resolve_effective_rejects_unmonitored_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    with pytest.raises(HTTPException) as exc:
        await resolve_effective_subscription_ids(selected_subscription_ids=["sub-x"])
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_resolve_effective_applies_rbac_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a", "sub-b", "sub-c"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    result = await resolve_effective_subscription_ids(
        allowed_subscriptions=["sub-a", "sub-b"],
        selected_subscription_ids=["sub-b"],
    )
    assert result == ["sub-b"]


@pytest.mark.anyio
async def test_resolve_effective_rejects_rbac_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a", "sub-b"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    with pytest.raises(HTTPException) as exc:
        await resolve_effective_subscription_ids(
            allowed_subscriptions=["sub-a"],
            selected_subscription_ids=["sub-b"],
        )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_get_scoped_uses_context_when_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a", "sub-b"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    token = set_scoped_subscription_ids(["sub-b"])
    try:
        assert await get_scoped_subscription_ids() == ["sub-b"]
    finally:
        reset_scoped_subscription_ids(token)


@pytest.mark.anyio
async def test_get_scoped_falls_back_to_monitored_without_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    assert await get_scoped_subscription_ids() == ["sub-a"]


@pytest.mark.anyio
async def test_manual_amortized_sync_omits_ids_when_scope_is_full_monitored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a", "sub-b"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.scoped_subscription_ids = ["sub-a", "sub-b"]

    assert await subscription_ids_for_manual_amortized_sync(request) is None


@pytest.mark.anyio
async def test_manual_amortized_sync_returns_subset_when_scope_narrowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_monitored() -> list[str]:
        return ["sub-a", "sub-b", "sub-c"]

    monkeypatch.setattr(
        "app.core.subscription_scope.get_monitored_subscription_ids",
        fake_monitored,
    )

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.scoped_subscription_ids = ["sub-b", "sub-c"]

    assert await subscription_ids_for_manual_amortized_sync(request) == ["sub-b", "sub-c"]
