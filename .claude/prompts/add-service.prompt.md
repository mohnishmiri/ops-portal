---
description: "Add a backend service module in the Azure Ops Portal. Use when creating business-logic helpers or thin service classes under backend/app/services."
argument-hint: "Describe the domain, inputs, dependencies, and expected outputs"
agent: "agent"
---

# Add a Backend Service

Create a new service module for the Azure Ops Portal backend.

## Context
- Services live in `backend/app/services/<domain>_service.py`
- Route handlers stay thin; business logic belongs in services
- This repo mixes functional services and thin service classes, so match the surrounding domain
- Pass dependencies in explicitly (`AsyncSession`, Redis clients, config, Azure credential helpers)
- Use local import style: `from app...`

## Steps
1. Create or extend `backend/app/services/{{domain}}_service.py`
2. Follow the closest existing service in the same domain before inventing a new abstraction
3. Use `structlog.get_logger()` for logging; never `print()`
4. Keep state external unless the domain already uses a service class with constructor-injected dependencies
5. Translate Azure SDK failures into `HTTPException`, domain errors, or structured return values that the router can handle cleanly
6. Add full type annotations
7. Create or extend schemas only when the service returns structured API-facing data
8. Write unit tests in `backend/tests/test_{{domain}}_service.py`

## Template
```python
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.{{domain}} import {{Model}}
from app.schemas.{{domain}} import {{Schema}}Create, {{Schema}}Response

logger = structlog.get_logger()


async def get_all_{{resource}}(session: AsyncSession) -> list[{{Schema}}Response]:
    """Retrieve all {{resource}}."""
    logger.info("fetching_{{resource}}")
    result = await session.execute(select({{Model}}))
    rows = result.scalars().all()
    return [{{Schema}}Response.model_validate(r) for r in rows]


async def create_{{resource}}(
    session: AsyncSession, data: {{Schema}}Create
) -> {{Schema}}Response:
    """Create a new {{resource}} record."""
    obj = {{Model}}(**data.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    logger.info("created_{{resource}}", id=str(obj.id))
    return {{Schema}}Response.model_validate(obj)
```

## Variables
- `domain`: snake_case domain name (e.g., `resource_tag`)
- `resource`: plural REST resource name (e.g., `resource_tags`)
- `Model`: SQLAlchemy model class
- `Schema`: Pydantic schema base name

## Verify
- Lint: `uv run ruff check app/`
- Type-check: `uv run mypy app/ --ignore-missing-imports`
- Tests: `uv run pytest tests/ -v --tb=short`

## Acceptance Criteria
- [ ] All functions are `async def` with full type annotations
- [ ] Uses `structlog` for logging
- [ ] Azure SDK exceptions caught and translated
- [ ] No global state — dependencies passed as parameters
- [ ] Unit test file created with ≥1 happy-path and ≥1 error test
- [ ] Passes `ruff check` and `mypy --strict`
