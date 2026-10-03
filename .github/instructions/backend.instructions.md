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

## Authorization (read before adding or changing a route)

Access has two dimensions; both are enforced server-side. See
`backend/app/docs/access_control_README.md` for the full guide.

- **What** — roles form a ladder `SUPER_ADMIN ⊃ ADMIN ⊃ WRITE ⊃ READ`
  (`require_role`). READ views everything, WRITE makes every change on
  operational pages including deletes, and `/admin` + `/permissions` are
  `SUPER_ADMIN` only. `tests/test_role_matrix.py` enforces this for every route.
- **Where** — users see and change only the subscriptions granted to them
  (project / app × Prod / Non-Prod). `enforce_target_access` already checks any
  ARM ID, `subscription_id`-like field or Key Vault named in path, query or JSON
  body.
- **Row loaded by database ID?** After loading it, call
  `assert_resource_access(row.<arm id or subscription column>, "read" | "write")`
  from `app.core.access_scope`. Filter lists with `arm_scope_clause(...)` /
  `subscription_scope_clause(...)`.
- **POST/PUT that changes nothing in Azure** (cache refresh, local render, the
  caller's own preference)? Add it to `READ_PERMITTED_MUTATIONS` in
  `app/core/route_policy.py` with a reason.
- **Destructive operation?** Add a capability to `CAPABILITY_SEEDS` and guard the
  route with `require_capability(...)`.
- **Never** treat an empty subscription list as "all", and never populate
  `UserContext.allowed_subscriptions`. Cache keys for scoped data must include
  the effective scope. Syncs that delete stale rows must stay within the
  subscriptions they synced.
- **WebSocket routes** skip router dependencies, so check access in the handler.
- **New column on an existing table** → a new idempotent `.sql` file in
  `backend/migrations/` (`create_all` never adds columns).

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
- `backend/app/core/authz.py` (portal gate, module gate, capabilities)
- `backend/app/core/access_scope.py` (project / subscription grants, row helpers)
- `backend/app/core/target_access.py` (subscriptions named in a request)
- `backend/app/core/route_policy.py` (read-only mutations)
- `backend/app/core/subscription_resolver.py` (admin monitored set; sync jobs)
- `backend/app/core/subscription_scope.py` (per-request read scope)
- `backend/app/docs/access_control_README.md`
- `backend/README.md`
- `docs/access-control-design.md`, `docs/PROJECT_ACCESS.md`
- `.github/workflows/ci-cd.yaml`
