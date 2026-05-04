---
name: "Debug Auth"
description: "Debug Entra ID, MSAL, JWT validation, or RBAC issues in the Azure Ops Portal. Use for 401/403 errors, login redirect problems, token handling bugs, and dev-mode auth confusion."
argument-hint: "Describe the auth symptom, expected behavior, and where it fails"
agent: "agent"
---

# Debug Auth

Diagnose and fix an authentication or authorization problem in the Azure Ops Portal.

Use `Auth_Buddy` when you want a dedicated auth specialist persona for the investigation.

## Scope

- Frontend MSAL configuration and redirect behavior
- ID token acquisition and request injection
- Backend JWT validation and JWKS lookup
- Role mapping and RBAC checks
- Development-mode auth bypass behavior

## Workflow

1. Identify the exact symptom.
   - Login redirect loop
   - Silent token acquisition failure
   - API requests missing `Authorization`
   - Backend 401/403 responses
   - Role-gated action blocked unexpectedly
2. Trace the auth path end-to-end.
   - Frontend: `frontend/src/config/authConfig.ts` -> `frontend/src/services/apiClient.ts` -> `frontend/src/App.tsx`
   - Backend: `backend/app/auth/__init__.py` -> endpoint dependency in `backend/app/api/v1/endpoints/`
3. Check environment assumptions.
   - Is the app in dev mode?
   - Are the redirect URI and API base URL correct?
   - Are the expected roles present in the token claims?
4. Apply the minimal fix.
   - Prefer fixing configuration and dependency wiring before refactoring
   - Do not change unrelated business logic
5. Verify the fix.
   - Frontend: `npm run lint`, `npm run build`
   - Backend: `uv run ruff check app/`, `uv run pytest tests/ -v --tb=short`

## Inputs

- `SYMPTOM`: what the user sees
- `EXPECTED_BEHAVIOR`: what should happen instead
- `AFFECTED_FILE`: optional starting point
- `ERROR_TEXT`: optional exact error or HTTP status

## Acceptance Criteria

- [ ] Failure point identified precisely
- [ ] Fix is minimal and scoped to auth/RBAC behavior
- [ ] Verification steps are listed
- [ ] No secrets or tokens are exposed in the response
