---
description: "Use when writing backend tests, API tests, or deciding whether a frontend test harness should be introduced. Covers current pytest patterns, import paths, mocking, and verification commands."
applyTo: "backend/tests/**/*.py"
---

# Test Instructions

- Backend test files live in `backend/tests/`.
- Import application modules via `app...`, not `backend.app...`.
- Use `pytest` and `pytest-asyncio` for async coverage.
- API tests should use `httpx.AsyncClient` with `ASGITransport(app=app)`.
- Mock Azure SDK calls, Redis access, and external HTTP requests. Do not make live Azure calls in tests.
- Prefer regression tests that fail before the fix and pass after it.
- **Subscription access in tests:** an autouse fixture in `conftest.py` gives
  every user unrestricted subscription access. Tests of grants, Prod / Non-Prod
  or project isolation must be marked `@pytest.mark.real_access`; they can build
  fixtures with `tests/access_helpers.py` (`build_world`, `grant`,
  `make_project_admin`, `client_as`).
- To see READ/WRITE behaviour through the API, turn the dev bypass off (the
  `strict_auth` fixture in `test_role_matrix.py`). With it on, `require_role`
  skips every check.
- The frontend has Vitest (`npm test` in `frontend/`).

## Verify (MANDATORY)

After **every** backend code change, run the following from `backend/` and fix all errors before completing the task:

- **Format (required):** `uv run ruff format --check app/` — must pass. If it fails, run `uv run ruff format app/` to auto-fix, then re-run the check.
- **Lint (required):** `uv run ruff check app/` — must pass with zero errors
- **Unit tests (required):** `uv run pytest tests/ -v --tb=short` — must pass with zero failures

> ⚠️ Never skip `ruff format --check`, `ruff check`, or `pytest`. All three must pass before marking work complete.

## Key References

- `backend/tests/conftest.py`, `backend/tests/access_helpers.py`
- `backend/tests/test_role_matrix.py` (portal-wide role policy)
- `backend/tests/test_access_scope.py`, `test_target_access.py`, `test_row_access.py`, `test_access_api.py`
- `backend/tests/test_api.py`
- `backend/tests/test_api_manual.py`
- `backend/tests/test_import.py`
- `backend/tests/test_models.py`
