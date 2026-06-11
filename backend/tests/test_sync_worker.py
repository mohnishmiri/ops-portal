"""Tests for sync worker job dispatch and already-running handling."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import sync_worker


@pytest.mark.anyio
async def test_await_full_sync_result_waits_for_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    job = SimpleNamespace(id=1, job_type="amortized")
    calls = {"count": 0}

    async def fake_run_sync() -> dict:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"status": "already_running", "message": "Another amortized cost sync is in progress"}
        return {"status": "completed", "rows_synced": 10}

    monkeypatch.setattr(sync_worker, "_ALREADY_RUNNING_WAIT_SECONDS", 0)

    status, error, result = await sync_worker._await_full_sync_result(job, fake_run_sync)

    assert status == "completed"
    assert error is None
    assert result == {"status": "completed", "rows_synced": 10}
    assert calls["count"] == 2


@pytest.mark.anyio
async def test_await_full_sync_result_surfaces_message_on_failure() -> None:
    job = SimpleNamespace(id=2, job_type="amortized")

    async def fake_run_sync() -> dict:
        return {"status": "failed", "message": "Azure amortized sync failed — HTTP 429"}

    status, error, result = await sync_worker._await_full_sync_result(job, fake_run_sync)

    assert status == "failed"
    assert error == "Azure amortized sync failed — HTTP 429"
    assert result["status"] == "failed"
