"""Standalone TP01 containment tests independent of governed persistence imports."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

from migration_intake.application.dto import ActorContext
from migration_intake.web.security import Capability, require_capability


class SpyService:
    """Record whether a denied request reached a state-changing service."""

    def __init__(self) -> None:
        self.upload_calls = 0
        self.generate_calls = 0
        self.approval_calls = 0

    def upload(self) -> None:
        self.upload_calls += 1

    def generate(self) -> None:
        self.generate_calls += 1

    def approve(self) -> None:
        self.approval_calls += 1


async def _read_upload_with_limit(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await upload.read(min(chunk_size, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="File too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _app(
    *,
    capabilities: frozenset[str] = frozenset(),
    generation_enabled: bool = False,
    max_upload_bytes: int = 32,
) -> tuple[FastAPI, SpyService]:
    app = FastAPI()
    service = SpyService()
    actor = ActorContext(actor_id="00000000-0000-0000-0000-000000000001", role_codes=capabilities)

    @app.post("/upload")
    async def upload(base_diagram: UploadFile) -> dict[str, str]:
        require_capability(set(actor.role_codes), Capability.TOPOLOGY_BASE_UPLOAD)
        await _read_upload_with_limit(base_diagram, max_upload_bytes)
        service.upload()
        return {"status": "stored"}

    @app.post("/generate")
    async def generate() -> dict[str, str]:
        require_capability(set(actor.role_codes), Capability.TOPOLOGY_GENERATE)
        if not generation_enabled:
            raise HTTPException(
                status_code=503,
                detail="Topology generation is disabled pending immutable pipeline certification",
            )
        service.generate()
        return {"status": "generated"}

    @app.post("/approve")
    async def approve() -> dict[str, str]:
        if not generation_enabled:
            raise HTTPException(
                status_code=503,
                detail="Topology generation is disabled pending immutable pipeline certification",
            )
        require_capability(set(actor.role_codes), Capability.TOPOLOGY_APPROVE)
        service.approve()
        return {"status": "approved"}

    @app.get("/history/{app_id}/{intake_id}/{run_id}")
    async def history(app_id: str, intake_id: str, run_id: str) -> dict[str, Any]:
        if (app_id, intake_id, run_id) != ("app-1", "intake-1", "run-1"):
            raise HTTPException(status_code=404, detail="Generation run not found")
        require_capability(set(actor.role_codes), Capability.TOPOLOGY_ARTIFACT_DOWNLOAD)
        return {"authority": "LEGACY_UNPINNED", "read_only": True}

    return app, service


def test_upload_denies_before_read_or_write() -> None:
    app, service = _app()

    with TestClient(app) as client:
        response = client.post("/upload", files={"base_diagram": ("base.drawio", b"content")})

    assert response.status_code == 403
    assert service.upload_calls == 0


def test_upload_is_bounded_and_has_no_write_on_413() -> None:
    capabilities = frozenset({Capability.TOPOLOGY_BASE_UPLOAD.value})
    app, service = _app(capabilities=capabilities)

    with TestClient(app) as client:
        response = client.post("/upload", files={"base_diagram": ("base.drawio", b"x" * 33)})

    assert response.status_code == 413
    assert service.upload_calls == 0


@pytest.mark.parametrize("path", ["/generate", "/approve"])
def test_disabled_commands_fail_closed_without_writes(path: str) -> None:
    capabilities = frozenset(
        {Capability.TOPOLOGY_GENERATE.value, Capability.TOPOLOGY_APPROVE.value}
    )
    app, service = _app(capabilities=capabilities)

    with TestClient(app) as client:
        response = client.post(path)

    assert response.status_code == 503
    assert "immutable pipeline certification" in response.text
    assert service.generate_calls == 0
    assert service.approval_calls == 0


def test_historical_access_is_scoped_permissioned_and_unverified() -> None:
    capabilities = frozenset({Capability.TOPOLOGY_ARTIFACT_DOWNLOAD.value})
    app, _ = _app(capabilities=capabilities)

    with TestClient(app) as client:
        visible = client.get("/history/app-1/intake-1/run-1")
        wrong_scope = client.get("/history/app-2/intake-1/run-1")

    assert visible.status_code == 200
    assert visible.json() == {"authority": "LEGACY_UNPINNED", "read_only": True}
    assert wrong_scope.status_code == 404


def test_historical_access_requires_download_capability() -> None:
    app, _ = _app()

    with TestClient(app) as client:
        response = client.get("/history/app-1/intake-1/run-1")

    assert response.status_code == 403
