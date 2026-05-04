---
description: Add or refactor a dashboard chart using the repo's React Query, Tailwind, and Recharts patterns.
argument-hint: Describe the chart, page, metric source, filters, and desired interactions.
agent: agent
---

# Add Dashboard Chart

Add or refactor a dashboard chart for this repo using the existing frontend architecture.

## Context

- Frontend pages live in `frontend/src/pages/`.
- Shared feature UI often lives in `frontend/src/features/`.
- Data fetching should go through existing service modules in `frontend/src/services/`.
- Use React Query for server state.
- Use Recharts for visualizations.
- Style with Tailwind utilities and preserve the repo's existing UI patterns.

## Requirements

- Identify the page or feature component that should own the chart.
- Reuse an existing service hook if one already returns the required data.
- If the data contract is missing, add the smallest frontend service change necessary instead of inventing local mock data.
- Handle loading, empty, and error states cleanly.
- Use `ResponsiveContainer` and ensure the chart works on desktop and mobile.
- Use labels, legends, tooltips, and axis formatting when they improve clarity.
- Keep color choices aligned with the current app theme rather than arbitrary defaults.

## Deliverables

- The chart component or page update.
- Any supporting service/types changes needed for the chart.
- A short explanation of data flow: page/component -> service hook -> API.
- Verification steps using the repo's frontend commands.

## Verify

From `frontend/`:

```bash
npm run lint
npm run build
```