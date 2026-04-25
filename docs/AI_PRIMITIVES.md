# AI Primitives Index

This repo includes reusable Copilot prompts and custom agents under `.github/`.

Use this file as a quick chooser when you want to start the right workflow without guessing.

## Prompts

| Primitive | Use It When | Notes |
| --- | --- | --- |
| `.github/prompts/add-api-endpoint.prompt.md` | You need a new FastAPI endpoint, router wiring, schemas, and service integration. | Best for backend API additions under `backend/app/api/v1/endpoints/`. |
| `.github/prompts/add-azure-service-integration.prompt.md` | You need to call a new Azure API or extend an Azure-backed backend workflow. | Focuses on service-layer integration, credentials, throttling, and error handling. |
| `.github/prompts/add-dashboard-chart.prompt.md` | You need a new chart or want to refactor an existing dashboard visualization. | Geared toward React Query + Recharts + Tailwind patterns in the frontend. |
| `.github/prompts/add-database-model.prompt.md` | You need to add or extend a SQLAlchemy model. | Useful for `backend/app/models/` work and related schema updates. |
| `.github/prompts/add-new-page.prompt.md` | You need to scaffold a new React page and route. | Covers page placement, API service wiring, and route registration in `frontend/src/App.tsx`. |
| `.github/prompts/add-new-plugin.prompt.md` | You need a new backend plugin package. | Matches the repo's `PluginBase` and `create_plugin()` discovery pattern. |
| `.github/prompts/add-service.prompt.md` | You need a backend service module or want to move business logic out of a route. | Best for `backend/app/services/` additions or cleanup. |
| `.github/prompts/debug-auth.prompt.md` | You are debugging login loops, missing tokens, 401/403 errors, RBAC mismatches, or dev-mode auth behavior. | Covers frontend MSAL and backend JWT/RBAC flow together. |
| `.github/prompts/fix-bug.prompt.md` | You have a concrete bug and want a structured diagnose-fix-verify workflow. | Good default for cross-layer debugging. |
| `.github/prompts/write-tests.prompt.md` | You need backend pytest coverage or a clearly scoped test addition. | Prefer this for API tests, service tests, and regression coverage. |
| `.github/prompts/custom-agent-prompt.md` | You want to design a brand-new custom agent prompt file. | Reference template only; not a repo-specific execution workflow. |

## Agents

| Primitive | Use It When | Notes |
| --- | --- | --- |
| `.github/agents/Auth_Buddy.agent.md` | You want a focused auth specialist for Entra ID, MSAL, JWT validation, RBAC, or 401/403 debugging. | Best paired with auth-related frontend and backend tracing. |
| `.github/agents/DataFlow_Buddy.agent.md` | You need architecture docs, Mermaid diagrams, request traces, or data-flow mapping. | Useful for documenting how features move across frontend, backend, Azure, and storage layers. |
| `.github/agents/Endpoint_Buddy.agent.md` | You want to discover, test, monitor, or review service endpoints and health behavior. | Best for endpoint inventories, connectivity checks, and failure analysis. |
| `.github/agents/UI_Buddy.agent.md` | You want a UI consistency, accessibility, theme, or dashboard polish audit. | Useful for grids, charts, responsive behavior, icon cleanup, and visual standardization. |

## Quick Picks

- Building a new API feature end-to-end: start with `.github/prompts/add-api-endpoint.prompt.md`
- Adding Azure-backed backend logic without a new route yet: start with `.github/prompts/add-azure-service-integration.prompt.md`
- Adding a page plus visualization: use `.github/prompts/add-new-page.prompt.md` and `.github/prompts/add-dashboard-chart.prompt.md`
- Untangling auth failures: use `.github/prompts/debug-auth.prompt.md` or `.github/agents/Auth_Buddy.agent.md`
- General bug hunt: use `.github/prompts/fix-bug.prompt.md`
- Test coverage after backend changes: use `.github/prompts/write-tests.prompt.md`
- UI cleanup or enterprise polish: use `.github/agents/UI_Buddy.agent.md`
- Architecture or sequence diagrams: use `.github/agents/DataFlow_Buddy.agent.md`

## Scoped Instructions

These are not user-invoked prompts, but they are important because Copilot uses them automatically when edits match their scope:

- `.github/instructions/backend.instructions.md`
- `.github/instructions/frontend.instructions.md`
- `.github/instructions/plugins.instructions.md`
- `.github/instructions/tests.instructions.md`

In practice, that means prompt output should already be shaped by the relevant backend, frontend, plugin, or test conventions for this repo.
