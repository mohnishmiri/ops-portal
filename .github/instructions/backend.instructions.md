---
description: "Use when editing FastAPI endpoints, services, auth wiring, database access, or background jobs in the backend. Covers import style, router registration, service boundaries, and verification commands."
applyTo: "backend/app/**/*.py, backend/tests/**/*.py"
---

# Backend Instructions

- Use `from app...` imports, not `from backend.app...`.
- Route modules live in `backend/app/api/v1/endpoints/` and are wired into `backend/app/api/v1/router.py`.
- Auth dependencies come from `app.auth`.
- Database dependencies come from `app.core.database`.
- Keep route handlers thin. Put business logic in `backend/app/services/`.
- Match the surrounding domain style before introducing a new abstraction. This repo uses both helper functions and thin service classes.
- Use `structlog` for logging. Do not add `print()` calls.
- Handle Azure SDK failures in the service layer and return consistent domain errors to the router.
- Prefer explicit typing. When touching older model files, follow the local SQLAlchemy style instead of mixing patterns aggressively.
- Startup and scheduler behavior belongs in `backend/app/main.py` and service modules, not inside route handlers.

## SQLAlchemy Column Type Safety

When building queries against SQLAlchemy models, **always match the Python literal type to the column's SQL type**:

- If a column is `String` / `Text` (e.g. `cost_date = Column(String(10))`), compare it with a Python `str`, **not** a `datetime.date` or `datetime.datetime`. Use `.isoformat()` to convert dates to strings before passing them to `WHERE` clauses.
- If a column is `DateTime`, compare it with a `datetime` object.
- Mixing types causes PostgreSQL runtime errors like `operator does not exist: character varying >= date`.

**Example — CORRECT:**
```python
start_date = date(2026, 2, 19)
stmt = select(Model).where(Model.cost_date >= start_date.isoformat())  # String column
```

**Example — WRONG (causes ProgrammingError in PostgreSQL):**
```python
start_date = date(2026, 2, 19)
stmt = select(Model).where(Model.cost_date >= start_date)  # date vs String column
```

## Verify (MANDATORY)

After **every** backend code change, run the following from `backend/` and fix all errors before completing the task:

- Install/sync: `uv sync`
- **Format (required — two-step):**
  1. `uv run ruff format app/` — auto-format the **entire** `app/` directory (not just the files you edited).
  2. `uv run ruff format --check app/` — verify zero files need reformatting.
  > **Why both steps?** Editing one file can cause transitive formatting changes elsewhere (imports, line wrapping). Formatting only the changed file and running `--check` on the rest will miss those and **break CI**.
- **Lint (required):** `uv run ruff check app/` — must pass with zero errors.
- Type-check: `uv run mypy app/ --ignore-missing-imports`
- **Unit tests (required):** `uv run pytest tests/ -v --tb=short` — must pass with zero failures. On Windows, if the bare `pytest` entrypoint fails with a path-canonicalization error, use `uv run python -m pytest tests/ -v --tb=short` instead.

> ⚠️ Never skip `ruff format`, `ruff check`, or `pytest`. All three must pass before marking work complete.
> ⚠️ **Common CI failure:** Running `ruff format` on only a single file instead of the full `app/` directory. Always format everything.

## Key References

- `backend/app/main.py`
- `backend/app/api/v1/router.py`
- `backend/app/auth/__init__.py`
- `backend/app/core/database.py`
- `backend/app/core/subscription_resolver.py` (admin monitored set; sync jobs)
- `backend/app/core/subscription_scope.py` (per-request read scope)
- `backend/README.md`
- `docs/ARCHITECTURE.md` (§2.4 subscription scoping, §8 cost cleanup)
- `.github/workflows/ci-cd.yaml`
