---
description: Add a backend service integration with an Azure API while following the repo's async service, credential, and error-handling patterns.
argument-hint: Describe the Azure service, the capability to add, target endpoint or workflow, and expected response shape.
agent: agent
---

# Add Azure Service Integration

Implement a backend integration with an Azure service for this repo.

## Context

- Backend code lives under `backend/app/`.
- Route handlers should stay thin and delegate to `backend/app/services/`.
- Use the repo's existing auth, config, throttling, caching, and logging patterns where relevant.
- Prefer async-friendly code paths and avoid blocking the FastAPI event loop.
- Keep Azure-specific exception handling in the service layer and translate failures into clear API behavior.

## Requirements

- Determine whether the change belongs in an existing service or a new `*_service.py` module.
- Use the existing Azure credential approach; do not hard-code credentials or tokens.
- Reuse shared helpers for throttling, caching, database access, or subscription resolution when appropriate.
- If an endpoint is needed, wire it through the correct router module and keep request/response contracts explicit.
- Add or update tests for the service logic or endpoint behavior when the repo already has a suitable test pattern.
- Avoid speculative abstractions; implement only the pieces needed for the requested workflow.

## Deliverables

- Service-layer implementation.
- Any router, schema, or config updates required.
- Tests for changed backend behavior when feasible.
- A short explanation of where the Azure call happens and how failures are surfaced.

## Verify

From `backend/`:

```bash
uv run pytest
uv run ruff check .
```