---
description: "Add a new frontend page in the Azure Ops Portal React app. Use when scaffolding pages under frontend/src/pages with React Query and service wiring. For ATT-standard page creation, prefer the UI_Buddy page-builder workflow."
argument-hint: "Describe the page, API endpoint, route path, and required RBAC behavior"
agent: "agent"
---

# Add a New Frontend Page

Scaffold a new page component for the Azure Ops Portal React app.

## Preferred Path

If the new page should follow the repo's ATT-standard UI workflow, grid search/pagination rules, audit tracking guidance, or backend-mediated Ollama pattern, use the `ui-buddy-page-builder` skill and the `ui-buddy-page-builder` prompt instead of a generic scaffold.

## Context
- Frontend: React 18 + TypeScript, Vite, TailwindCSS
- Pages live in `frontend/src/pages/`
- Shared UI pieces live in `frontend/src/components/` and `frontend/src/features/`
- API services live in `frontend/src/services/`
- Styling should use Tailwind utilities and the existing ATT palette in `frontend/tailwind.config.js`
- The app is globally wrapped with MSAL auth; page-level work usually means route wiring and UI role gating rather than a separate auth shell
- ATT-standard pages should reuse shared `MetricCard`, `gridStyles`, and the repo's existing `audit_logs` and backend Ollama patterns through the UI_Buddy workflow

## Steps
1. Create `frontend/src/pages/{{PAGE_NAME}}.tsx` as a functional component
2. If the page fetches data, create or extend an API service in `frontend/src/services/{{domain}}Api.ts`
3. Use React Query (`useQuery` / `useMutation`) for all data fetching
4. Handle loading, error, and empty states explicitly
5. Add the route in `frontend/src/App.tsx`
6. Gate UI actions or page visibility by RBAC role if needed (Admin / Write / Read)
7. Use `ResponsiveContainer` with Recharts if the page includes charts
8. Keep the page focused; extract feature components early if it grows

## Variables
- `PAGE_NAME`: PascalCase component name (e.g., `ResourceTaggingPage`)
- `API_ENDPOINT`: backend route this page calls (e.g., `/api/v1/resource-tags`)
- `REQUIRED_ROLE`: minimum RBAC role to access the page (Admin | Write | Read)

## Template
```tsx
import { useQuery } from "@tanstack/react-query";
import apiClient from "../services/apiClient";

export default function {{PAGE_NAME}}() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["{{queryKey}}"],
    queryFn: () => apiClient.get("{{API_ENDPOINT}}").then((r) => r.data),
  });

  if (isLoading) return <div className="p-6">Loading…</div>;
  if (isError) return <div className="p-6 text-red-600">Error: {String(error)}</div>;

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">{{PAGE_NAME}}</h1>
      {/* Render data here */}
    </div>
  );
}
```

## Acceptance Criteria
- [ ] TypeScript strict mode — no `any`
- [ ] Uses React Query (not raw `useEffect` + `fetch`)
- [ ] TailwindCSS styling only
- [ ] Loading and error states handled
- [ ] Route added in `frontend/src/App.tsx`
- [ ] Any RBAC handling matches the existing app patterns
- [ ] Passes ESLint
