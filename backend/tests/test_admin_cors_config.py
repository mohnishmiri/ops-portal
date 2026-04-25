import pytest
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from app.core.admin_config import parse_cors_origins, serialize_cors_origins
from app.middleware.dynamic_cors import DynamicCORSMiddleware


def test_parse_cors_origins_accepts_json_and_deduplicates() -> None:
    raw = '["http://localhost:5173", "http://localhost:5173/", "http://127.0.0.1:5173"]'

    assert parse_cors_origins(raw, strict=True) == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert serialize_cors_origins(["http://localhost:5173", "http://127.0.0.1:5173"]) == (
        '["http://localhost:5173", "http://127.0.0.1:5173"]'
    )


def test_parse_cors_origins_rejects_invalid_and_wildcard() -> None:
    with pytest.raises(ValueError):
        parse_cors_origins("*", strict=True)

    with pytest.raises(ValueError):
        parse_cors_origins("localhost:5173", strict=True)


@pytest.mark.anyio
async def test_dynamic_cors_middleware_refreshes_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def app(scope, receive, send):
        response = JSONResponse({"ok": True})
        await response(scope, receive, send)

    async def fake_get_db_session():
        yield object()

    async def fake_get_effective_cors_origins(_db):
        return ["http://localhost:5173"]

    monkeypatch.setattr("app.middleware.dynamic_cors.get_db_session", fake_get_db_session)
    monkeypatch.setattr(
        "app.middleware.dynamic_cors.get_effective_cors_origins",
        fake_get_effective_cors_origins,
    )

    wrapped = DynamicCORSMiddleware(
        app,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
        refresh_seconds=0,
    )

    transport = ASGITransport(app=wrapped)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
