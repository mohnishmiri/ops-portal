---
description: "Write tests for the Azure Ops Portal. Use when adding backend pytest coverage or when introducing a clearly scoped frontend test harness."
argument-hint: "Describe the target file, behavior to cover, and whether you want unit, integration, or API tests"
agent: "agent"
---

# Write Tests

Generate tests for existing or new code in the Azure Ops Portal.

## Context
- **Backend tests:** pytest + pytest-asyncio, located in `backend/tests/`
- **API tests:** use `httpx.AsyncClient` with `ASGITransport` against the FastAPI app
- **Mocking:** `unittest.mock.AsyncMock` for async dependencies; `respx` for HTTP mocks
- **Coverage target:** ≥ 80%
- **Frontend tests:** no standardized frontend test harness is configured in `frontend/package.json` right now; prefer backend coverage or explicitly call out any new frontend test dependency you introduce

## Instructions
Given the file or function to test, generate comprehensive tests following these rules:

### Backend Tests
1. File naming: `test_<module>.py` in `backend/tests/`
2. Use `@pytest.mark.asyncio` for all async test functions
3. Arrange-Act-Assert pattern with clear sections
4. Mock external dependencies (Azure SDK, database sessions, Redis)
5. Test happy path, edge cases, and error conditions
6. Assert on:
   - Return values / response bodies
   - HTTP status codes for API tests
   - Side effects (DB writes, cache updates)
   - Exception types and messages
7. Use fixtures for common setup (DB session, authenticated client)

### Template (API Test)
```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_{{endpoint_name}}_returns_200():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/{{resource}}")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_{{endpoint_name}}_unauthorized_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/{{resource}}",
            headers={"Authorization": "Bearer invalid"},
        )
    assert response.status_code == 401
```

### Template (Service Test)
```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.{{domain}}_service import {{function_name}}


@pytest.mark.asyncio
async def test_{{function_name}}_happy_path():
    mock_session = AsyncMock()
    # Arrange: set up mock return values
    # Act
    result = await {{function_name}}(mock_session, ...)
    # Assert
    assert result is not None
    mock_session.execute.assert_called_once()
```

## Variables
- `TARGET_FILE`: the file or function to test
- `TEST_SCOPE`: unit | integration | api

## Acceptance Criteria
- [ ] Tests cover happy path + at least one error case
- [ ] All tests are async where applicable
- [ ] External calls are mocked — no real Azure/DB calls
- [ ] Passes `pytest` with no warnings
- [ ] Passes `uv run ruff check app/` and `uv run pytest tests/ -v --tb=short`
