# Copilot Instructions — Azure Ops Portal

> Auto-loaded every session. Use this file for stable repo-wide rules. For area-specific guidance, defer to the scoped instruction files in `.github/instructions/`.

---

## How To Use These Instructions

- Treat this file as the top-level policy layer.
- When editing backend code, also follow `.github/instructions/backend.instructions.md`.
- When editing frontend code, also follow `.github/instructions/frontend.instructions.md`.
- When editing plugins, also follow `.github/instructions/plugins.instructions.md`.
- When writing backend tests, also follow `.github/instructions/tests.instructions.md`.
- Prefer the scoped instructions over repeating file-path-specific rules here.

---

## Repo-Wide Rules

- Follow existing project conventions exactly. Do not introduce new frameworks, state managers, or ORMs without explicit approval.
- Keep changes small, reviewable, and easy to verify.
- Always add or update tests when changing backend logic or other test-covered behavior.
- Never commit secrets, tokens, or connection strings. Use environment variables or Azure Key Vault.
- Preserve the existing FastAPI + React + Azure architecture rather than inventing parallel patterns.

---

## Backend Defaults

- Python version target is 3.11+.
- Use `uv` for dependency management and command execution.
- Use Ruff for formatting and linting, and keep strict typing where the module already expects it.
- Use `structlog` for diagnostics; do not add `print()` debugging.
- Keep route handlers thin and put business logic in services.
- Use async database access and avoid blocking the event loop.
- Prefer Pydantic models over ad hoc dict request/response handling.

---

## Frontend Defaults

- Use TypeScript strict-mode-friendly code and avoid `any` unless unavoidable.
- Keep UI work within the existing React + Tailwind + React Query patterns.
- Route API calls through the shared API client and domain service files.
- Handle loading, empty, and error states for API-driven views.
- Use Recharts for charts already present in the app; do not introduce a second charting library without approval.

---

## Azure And Security Defaults

- Use Azure SDK credentials from `DefaultAzureCredential` or the repo's existing auth flow; never hard-code credentials.
- Respect throttling and caching patterns already present in the backend services.
- All endpoints should remain authenticated unless explicitly designed as public.
- Use parameterized ORM/query patterns only; do not build SQL strings manually.
- Do not widen CORS or other security-sensitive configuration without a clear reason.

---

## Infra And Delivery Defaults

- Keep Helm changes environment-aware and avoid hard-coding image tags or secrets.
- Validate infra changes with the repo's normal local checks when possible.
- Keep CI/CD edits aligned with the existing workflow order and deployment gates.

---

## Git And PR Conventions

- Branch names follow `feature/<ticket>-<slug>`, `fix/<ticket>-<slug>`, or `infra/<slug>`.
- Commit messages should be imperative and concise.
- PRs should explain what changed, why it changed, and how to test it.

---

## Mandatory Verification

- **After every backend code change**, all agents **must** run **all three** of the following from the `backend/` directory and fix any reported issues before considering the task complete:
  1. **Format (auto-fix then verify):** Run `uv run ruff format app/` first to auto-format **all** files, then run `uv run ruff format --check app/` to confirm zero reformats remain. **Always format the entire `app/` directory** — never format only individual changed files, because edits can trigger transitive formatting changes in imports or line wrapping across other files.
  2. **Lint:** `uv run ruff check app/` — must report zero errors.
  3. **Tests:** `uv run pytest tests/ -v --tb=short` — must pass with zero failures. On Windows, if `pytest` fails to canonicalize the script path, use `uv run python -m pytest tests/ -v --tb=short` instead.
- **After every frontend code change**, all agents **must** run `npx tsc --noEmit` from the `frontend/` directory and fix any reported issues before considering the task complete.
- Do not skip these checks. Do not mark a task as done until all format, lint, test, and type-check verification passes.
- **Common pitfall:** Running `ruff format` on only the file you edited and assuming the rest are clean. Always run against the full `app/` directory to catch all formatting drift.

---

## Guardrails

1. No secrets in code, fixtures, screenshots, or logs.
2. No destructive data or infrastructure changes without explicit user intent.
3. No speculative repo structure changes when the current codebase already has a working pattern.
4. No new dependencies unless the benefit clearly outweighs the maintenance cost.
5. No bypassing the scoped instruction files for backend, frontend, plugin, or test work.
6. No completing a task without running the mandatory verification checks listed above.
