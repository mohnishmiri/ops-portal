---
description: "Diagnose and fix a bug in the Azure Ops Portal. Use when tracing issues across FastAPI endpoints, services, React pages, MSAL auth, or Azure integrations."
argument-hint: "Describe the bug, error message, reproduction steps, and affected files if known"
agent: "agent"
---

# Fix a Bug

Diagnose and fix a bug in the Azure Ops Portal codebase.

## Context
- Backend: FastAPI + SQLAlchemy async + Azure SDK
- Frontend: React 18 + TypeScript + React Query
- Logs: structured JSON via `structlog` (backend), browser console (frontend)
- Backend tests use pytest; frontend verification currently relies on `npm run lint` and `npm run build` unless a test harness is added explicitly

## Workflow
1. **Reproduce** — Describe or reproduce the bug. Identify the affected layer (API, service, model, frontend component, auth, infra).
2. **Locate** — Trace the issue:
   - Backend: check route handler → service function → model/query → Azure SDK call
   - Frontend: check component → React Query hook → API service → network response
   - Check logs (`structlog` JSON output) for stack traces or error context
3. **Root Cause** — Identify why the bug occurs. Common causes:
   - Missing `await` on async calls
   - Pydantic schema mismatch (v2 breaking changes)
   - SQLAlchemy lazy loading in async context (`greenlet_spawn` error)
   - MSAL token expiry / silent acquisition failure
   - Azure API throttling (429 responses)
   - Stale React Query cache
4. **Fix** — Apply the minimal, targeted fix:
   - Do not refactor unrelated code in the same change
   - Match existing code style (ruff + mypy compliance)
   - If the fix changes an API contract, update the Pydantic schema
5. **Test** — Add a regression test that fails without the fix and passes with it
6. **Verify** — Run the relevant checks:
   - Backend: `uv run ruff check app/`, `uv run mypy app/ --ignore-missing-imports`, `uv run pytest tests/ -v --tb=short`
   - Frontend: `npm run lint`, `npm run build`

## Variables
- `BUG_DESCRIPTION`: what is going wrong
- `AFFECTED_FILE`: where the bug manifests (if known)
- `ERROR_MESSAGE`: exact error text or stack trace (if available)

## Acceptance Criteria
- [ ] Root cause identified and explained
- [ ] Fix is minimal and targeted
- [ ] Regression test added
- [ ] Passes the relevant repo checks (`ruff`, `mypy`, `pytest`, `eslint`, `build`)
- [ ] No unrelated changes included
