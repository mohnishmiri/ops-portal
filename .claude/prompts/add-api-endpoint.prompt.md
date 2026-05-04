---
description: "Add a FastAPI endpoint in the Azure Ops Portal backend. Use when creating schemas, services, endpoint handlers, and router registration under backend/app/api/v1/endpoints."
argument-hint: "Describe the resource, HTTP method, request/response shape, and auth rules"
agent: "agent"
---

# Add an API Endpoint

Create a new FastAPI endpoint for the Azure Ops Portal backend.

## Context
- Backend: FastAPI, Python 3.11+, all handlers are `async def`
- Route files live in `backend/app/api/v1/endpoints/`
- Routers are aggregated in `backend/app/api/v1/router.py`
- Business logic lives in `backend/app/services/<domain>_service.py`
- Schemas and typed payloads live in `backend/app/schemas/` or `backend/app/models/` depending on the domain
- Auth and RBAC dependencies come from `app.auth`
- Database dependencies come from `app.core.database`

## Steps
1. **Inspect the target domain first**
   - Reuse the nearest existing endpoint module in `backend/app/api/v1/endpoints/`
   - Match the local import style: `from app...`, not `from backend.app...`
2. **Schema** — Define or extend request/response models in `backend/app/schemas/{{domain}}.py`
   - Prefer Pydantic v2 models with explicit types
   - Use `model_config = ConfigDict(from_attributes=True)` when validating ORM objects
3. **Service** — Implement business logic in `backend/app/services/{{domain}}_service.py`
   - Keep route handlers thin
   - Catch Azure SDK exceptions in the service layer and translate them to domain-appropriate errors
4. **Router** — Add the endpoint in `backend/app/api/v1/endpoints/{{domain}}.py`
   - Route modules usually declare `router = APIRouter()` and rely on `backend/app/api/v1/router.py` for prefixes
   - Use `Depends(get_current_user)` or `Depends(require_role(...))` from `app.auth`
   - Use `Depends(get_db)` from `app.core.database` only when the endpoint actually needs a database session
   - Return appropriate HTTP status codes and response models
5. **Register Router** — Wire the module into `backend/app/api/v1/router.py`
6. **Tests** — Add tests in `backend/tests/test_{{domain}}.py`
   - Use `httpx.AsyncClient` with `ASGITransport`
   - Mock Azure calls with `AsyncMock`
7. **Docs** — Endpoint auto-appears in `/api/docs` outside production; add a concise summary/docstring

## Variables
- `RESOURCE`: REST resource name (plural, e.g., `budgets`)
- `HTTP_METHOD`: GET | POST | PUT | PATCH | DELETE
- `DESCRIPTION`: what the endpoint does

## Template (router)
```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.database import get_db
from app.models.auth import UserContext
from app.schemas.{{domain}} import {{Schema}}Request, {{Schema}}Response
from app.services.{{domain}}_service import {{function_name}}

router = APIRouter()


@router.{{HTTP_METHOD}}(
   "/{{path_suffix}}",
   response_model={{Schema}}Response,
   status_code=status.HTTP_200_OK,
   summary="{{DESCRIPTION}}",
)
async def {{handler_name}}(
    payload: {{Schema}}Request,
   user: UserContext = Depends(get_current_user),
   session: AsyncSession | None = Depends(get_db),
) -> {{Schema}}Response:
    """{{DESCRIPTION}}"""
    return await {{function_name}}(session, payload, user)
```

## Verify
- Backend install/test: `uv sync`
- Lint: `uv run ruff check app/`
- Type-check: `uv run mypy app/ --ignore-missing-imports`
- Tests: `uv run pytest tests/ -v --tb=short`

## Acceptance Criteria
- [ ] Pydantic v2 schemas with type annotations
- [ ] Async handler + service function
- [ ] Auth dependency applied
- [ ] Router registered in `backend/app/api/v1/router.py`
- [ ] Proper HTTP status codes
- [ ] At least one test with `httpx.AsyncClient`
- [ ] Passes `ruff check` and `mypy --strict`
