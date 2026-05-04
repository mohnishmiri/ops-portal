---
description: "Update an existing page to ATT standards using the UI_Buddy page-builder workflow. Use when modernizing a page, standardizing grids, adding ATT KPI cards, wiring audit tracking, or adding backend-mediated Ollama insights where useful."
argument-hint: "Describe the page or route, the UI gaps to fix, the grids to standardize, backend mutation needs, audit expectations, and whether AI insights should be added"
agent: "agent"
---

# UI_Buddy Update Existing Page

Use the `ui-buddy-page-builder` skill to modernize an existing page so it conforms to the repo's ATT standards and UI_Buddy rules.

## Required Outcomes

- Preserve existing business behavior unless the request explicitly changes it.
- Upgrade the page shell and shared UI to ATT standards.
- Ensure every page grid has top-right search and bottom pagination.
- Reuse shared components such as `MetricCard` and `gridStyles` instead of creating parallel UI patterns.
- Ensure tracked backend actions use the existing `audit_logs` infrastructure.
- Use backend-mediated Ollama integration only when it materially improves the page experience.

## Workflow

1. Inspect the existing page, route, hooks, services, and shared UI.
2. Apply the `ui-buddy-page-builder` skill.
3. Identify visual gaps against UI_Buddy standards.
4. Standardize grids, cards, chart presentation, icons, and ATT shell patterns.
5. If backend changes are required, confirm audit coverage and use existing `AuditLog` patterns when richer business-event tracking is needed.
6. If AI insight is useful, follow the repo's backend Ollama service pattern and keep a safe fallback.
7. Validate the touched code paths.

## Deliverables

- Updated page implementation.
- ATT compliance summary.
- Grid compliance summary for search and pagination.
- Audit decision summary.
- Ollama decision summary.
- Validation results.