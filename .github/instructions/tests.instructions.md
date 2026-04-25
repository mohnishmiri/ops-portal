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
- The repo does not currently expose a standard frontend test script in `frontend/package.json`; do not assume Vitest is available unless you add and justify it.

## Verify (MANDATORY)

After **every** backend code change, run the following from `backend/` and fix all errors before completing the task:

- **Format (required):** `uv run ruff format --check app/` — must pass. If it fails, run `uv run ruff format app/` to auto-fix, then re-run the check.
- **Lint (required):** `uv run ruff check app/` — must pass with zero errors
- **Unit tests (required):** `uv run pytest tests/ -v --tb=short` — must pass with zero failures

> ⚠️ Never skip `ruff format --check`, `ruff check`, or `pytest`. All three must pass before marking work complete.

## Key References

- `backend/tests/test_api.py`
- `backend/tests/test_api_manual.py`
- `backend/tests/test_import.py`
- `backend/tests/test_models.py`
