---
description: "Add a database model in the Azure Ops Portal backend. Use when creating or extending SQLAlchemy models in backend/app/models."
argument-hint: "Describe the model, key fields, relationships, and whether a migration is needed"
agent: "agent"
---

# Add a Database Model

Create a new SQLAlchemy 2 async model for the Azure Ops Portal.

## Context
- Models live in `backend/app/models/`
- The repo currently uses declarative `Base` from `backend/app/models/database.py`
- New code should prefer explicit typing and modern SQLAlchemy patterns where practical, but should still match the touched module's style
- Table names are snake_case plural
- Alembic is listed as a dependency, but migration scaffolding is not present in this workspace snapshot

## Steps
1. Create or extend a model file in `backend/app/models/{{domain}}.py`
2. Define the model class inheriting from `Base`
3. Prefer explicit type annotations; if the module already uses classic `Column(...)` patterns, match it rather than forcing a mixed style
4. Add relationships carefully and avoid introducing lazy-loading surprises into async code paths
5. Add or update any related schema in `backend/app/schemas/` when the model is API-facing
6. If Alembic is configured in the target environment, generate a migration with `uv run alembic revision --autogenerate -m "add {{table_name}} table"`
7. If Alembic is not configured yet, document that gap instead of inventing migration scaffolding in the prompt output

## Template
```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class {{ModelName}}(Base):
    __tablename__ = "{{table_name}}"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Add columns here
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

## Variables
- `ModelName`: PascalCase class name (e.g., `ResourceTag`)
- `table_name`: snake_case plural table name (e.g., `resource_tags`)

## Verify
- Lint: `uv run ruff check app/`
- Type-check: `uv run mypy app/ --ignore-missing-imports`

## Acceptance Criteria
- [ ] Matches the surrounding model style while keeping types explicit
- [ ] Table name is snake_case plural
- [ ] Has `id`, `created_at`, `updated_at` columns at minimum
- [ ] Related schema updated when needed
- [ ] Migration guidance matches the actual workspace setup
- [ ] Matching Pydantic schema created
- [ ] Passes `mypy --strict`
