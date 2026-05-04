---
description: "Use when editing React pages, feature components, frontend services, or app routing. Covers page locations, apiClient usage, React Query patterns, and ATT theme conventions."
applyTo: "frontend/src/**/*.ts, frontend/src/**/*.tsx"
---

# Frontend Instructions

- Pages live in `frontend/src/pages/`.
- Shared UI lives in `frontend/src/components/` and `frontend/src/features/`.
- Route registration happens in `frontend/src/App.tsx`.
- Import the API client as the default export: `import apiClient from \"../services/apiClient\"`.
- Prefer domain service wrappers in `frontend/src/services/*Api.ts` over inline axios calls in pages.
- Use React Query for server state and explicit loading, error, and empty states.
- Reuse the ATT palette from `frontend/tailwind.config.js` and existing Tailwind utility patterns.
- Match the current repo icon approach first. Reuse inline SVGs unless a new icon dependency is explicitly approved.
- Keep page components focused and extract large subsections into feature components.
- MSAL bootstrapping already happens at the app shell. Most page work needs route wiring and UI role gating, not a separate auth wrapper.

## Verify (MANDATORY)

After **every** frontend code change, run the following from `frontend/` and fix all errors before completing the task:

- **Type-check (required):** `npx tsc --noEmit` — must pass with zero errors
- Lint: `npm run lint`
- Build: `npm run build`

> ⚠️ Never skip type-check. If it reports errors, fix them before marking work complete.

## Key References

- `frontend/src/App.tsx`
- `frontend/src/services/apiClient.ts`
- `frontend/src/config/authConfig.ts`
- `frontend/tailwind.config.js`
- `frontend/package.json`
