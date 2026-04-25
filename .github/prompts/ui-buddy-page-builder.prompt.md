---
description: "Create or update an ATT-standard page using the UI_Buddy page-builder workflow. Use when you want a new page, a page refresh, or a full-stack page update with ATT UI, grid search, bottom pagination, audit tracking, and backend-mediated Ollama support where useful."
argument-hint: "Describe the page or route, data sources, grids, mutations, audit requirements, and whether AI insights are needed"
agent: "agent"
---

# UI_Buddy Page Builder

Use the `ui-buddy-page-builder` skill to create or update a page that follows the repo's ATT standards and UI_Buddy rules.

## Required Outcomes

- Match the AT&T visual standard already used in this repo.
- Reuse shared page, card, and grid primitives where available.
- Add search to the top-right of every grid.
- Add pagination below every grid.
- Ensure backend mutations are tracked through the existing `audit_logs` table path.
- Use backend-mediated Ollama integration when AI summaries, recommendations, or forecasts are valuable.

## Workflow

1. Inspect the existing route, page, related services, and shared components.
2. Apply the `ui-buddy-page-builder` skill.
3. Reuse `MetricCard`, `gridStyles`, React Query patterns, and existing backend services.
4. For any mutation or tracked workflow, confirm whether explicit `AuditLog` persistence is needed in addition to request middleware.
5. If AI is requested or materially useful, follow the backend Ollama service pattern already established in the repo.
6. Validate the touched code paths.

## Deliverables

- Updated route and page/component implementation.
- ATT compliance summary.
- Grid compliance summary for search and pagination.
- Audit decision summary.
- Ollama decision summary.
- Validation results.