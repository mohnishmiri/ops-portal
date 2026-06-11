---
name: ui-buddy-page-builder
description: "Use when creating a new page, updating an existing page, scaffolding ATT-standard UI, or wiring full-stack page changes for UI_Buddy. Covers AT&T design compliance, MetricCard usage, ATT grid shells, required grid search and bottom pagination, audit-log persistence via the existing audit_logs table, route/service wiring, and backend-mediated Ollama usage through https://customeraccountanalyser.test.att.com."
---

# UI_Buddy Page Builder

Use this skill when the request is to create or update a page and the result must follow the UI_Buddy agent standards and the repo's ATT design patterns.

## Intent

This skill standardizes page work across frontend and backend so every new or updated page:
- matches the AT&T visual system already enforced by UI_Buddy
- uses ATT-consistent KPI cards, tables, buttons, and charts
- adds search to every grid at the top right
- adds pagination below every grid
- preserves or adds auditability through the existing database audit log model
- prefers the repo's backend-mediated Ollama integration where AI-generated summaries or recommendations are useful
- sources subscription-scoped data via `get_scoped_subscription_ids()` (admin monitored set ∩ per-user picker), enforced in backend services rather than frontend-only filtering

## Non-Negotiable Rules

1. Follow the UI_Buddy agent rules first.
2. Reuse the repo's shared ATT UI primitives before building local variants.
3. Every grid must include:
   - search input in the grid header, aligned top right
   - pagination bar below the grid
   - ATT table shell from the shared grid styles when possible
4. If a page introduces backend actions, mutations, or tracked user workflows, the implementation must use the existing `audit_logs` table path rather than creating a second audit table.
5. If AI assistance is useful, prefer the backend Ollama integration pattern already used in the repo. Do not call the LLM directly from the browser.
6. Do not hardcode secrets, auth headers, or tokens.
7. Keep changes aligned with the existing React, FastAPI, SQLAlchemy, React Query, Tailwind, and ATT component patterns.
8. For subscription-scoped pages, use `get_scoped_subscription_ids()` in backend services (not `get_monitored_subscription_ids()` for reads). Sync jobs keep `get_monitored_subscription_ids()`. Frontend `SubscriptionContext` sends `subscription_ids` on GET via `apiClient`. See `docs/ARCHITECTURE.md` §2.4.

## Required References

Always inspect these files before implementation when they are relevant:
- `.github/agents/UI_Buddy.agent.md`
- `.github/instructions/frontend.instructions.md`
- `.github/instructions/backend.instructions.md`
- `frontend/src/components/gridStyles.tsx`
- `frontend/src/components/MetricCard.tsx`
- `frontend/src/App.tsx`
- `backend/app/models/database.py`
- `backend/app/middleware/audit.py`
- `backend/app/services/leadership_advisor_service.py`
- `backend/app/core/config.py`
- `.github/skills/ui-buddy-page-builder/templates/att-standard-page-template.tsx`
- `.github/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py`

## ATT UI Baseline

### Page Shell

- Use the existing page spacing and section cadence already present in the app.
- Prefer ATT palette tokens instead of arbitrary blues, purples, or ad hoc gray mixes.
- Favor elevated white surfaces with ATT-tinted borders and subtle ATT background treatments.

### KPI Cards

- Prefer `MetricCard` for small KPI or summary cards.
- Do not create flat one-off stat cards when `MetricCard` or the Key Vault KPI treatment is appropriate.
- Use SVG icons only.

### Grids

All tables must follow this minimum standard:
- ATT shell using `gridStyles.shell`
- header using `gridStyles.panelHeader`
- table using `gridStyles.table`
- ATT header cells using `gridStyles.headerCell` or `gridStyles.headerCellCenter`
- ATT row styling using `gridStyles.row`
- search input using `gridStyles.toolbarInput`
- bottom pager using `gridStyles.pager` and `gridStyles.pagerButton`

### Grid Requirements

For every grid on the page:
- search box must be in the top-right of the grid header
- pagination must be below the grid
- sorting should be added when the dataset is tabular and user-meaningful
- action columns are never sortable
- filtering and sorting must happen before pagination

### Charts

When adding or updating charts:
- use professional ATT-aligned colors
- include title, tooltip, legend, and clear axes when applicable
- avoid decorative-only graphs with missing labels or missing context

## Audit Logging Rule

This repo already has a shared audit table and middleware.

### Existing Audit Assets

- Database model: `backend/app/models/database.py` -> `AuditLog` with table `audit_logs`
- Middleware: `backend/app/middleware/audit.py`

### Required Audit Behavior

When page work includes backend changes such as create, update, delete, trigger, sync, approve, or configuration mutations:
- verify that request-level audit coverage exists through middleware
- if the action requires business-level audit detail beyond request logging, add an `AuditLog` record using the existing model
- do not create a new audit table if `audit_logs` already satisfies the requirement
- include structured `details` JSON with page name, feature name, entity identifiers, and the user-intent summary where appropriate

### Audit Checklist

Use this checklist during page work:
- Does the page add or change a backend mutation?
- Is the action already covered only by generic request middleware?
- Does the business event need richer structured details?
- If yes, add explicit `AuditLog` persistence using the existing table.

## Ollama Usage Rule

This repo already uses a backend Ollama pattern.

### Existing Ollama Assets

- Base URL default in `backend/app/core/config.py`: `https://customeraccountanalyser.test.att.com`
- Existing implementation pattern: `backend/app/services/leadership_advisor_service.py`

### Required Ollama Behavior

Use Ollama where it materially improves the page experience, for example:
- executive summaries
- recommendation narratives
- forecast commentary
- plain-English cost or compliance explanations
- contextual insight panels

Do this only through backend services and API endpoints.

Never:
- call the Ollama endpoint directly from the frontend
- embed auth headers in the page
- make the page dependent on Ollama for core rendering

Always:
- provide a non-LLM fallback state
- keep the base page functional without the model
- model the response shape explicitly in schemas and frontend types

## Workflow

### 1. Discovery

- Inspect the route target in `frontend/src/App.tsx`
- Identify shared components that should be reused
- Identify whether the change is frontend-only or full-stack
- Check if similar pages already exist and copy the established pattern instead of inventing a new one

### 2. Design Review

Before writing code, verify:
- page shell matches ATT styling
- KPI cards use `MetricCard` or the established equivalent
- every grid has a search box and bottom pager in the design plan
- charts follow ATT presentation standards
- icons are SVG-based and semantically colored

### 3. Backend Review

If the page needs backend support:
- keep route handlers thin
- place logic in services
- use Pydantic schemas
- use async DB access
- verify audit coverage via `audit_logs`
- use backend-mediated Ollama patterns when needed

### 4. Frontend Build Pattern

For grid-backed sections:
- derive `filteredRows` with `useMemo`
- derive `sortedRows` if sorting is present
- paginate after filter and sort
- reset page index when the search term changes or data size changes
- show empty states when no rows match

### 5. Verification

Frontend changes:
- run `npm run build` from `frontend`

Backend changes:
- run the repo's normal backend validation for touched files

Full-stack page changes:
- verify the route renders
- verify the grids have search and bottom pagination
- verify audit behavior for any mutation path
- verify Ollama-backed features degrade safely when unavailable

## Implementation Pattern

### ATT Grid Skeleton

```tsx
import { gridStyles } from "../components/gridStyles";

<div className={gridStyles.shell}>
  <div className={gridStyles.panelHeader}>
    <SectionTitle title="Example Grid" sub={`Showing ${pagedRows.length} of ${filteredRows.length}`} compact />
    <input
      type="text"
      value={search}
      onChange={(event) => setSearch(event.target.value)}
      placeholder="Search..."
      className={gridStyles.toolbarInput}
    />
  </div>
  <div className="overflow-x-auto">
    <table className={gridStyles.table}>
      <thead className={gridStyles.head}>
        <tr>
          <th className={gridStyles.headerCell}>Name</th>
          <th className={`${gridStyles.headerCell} text-right`}>Cost</th>
        </tr>
      </thead>
      <tbody>
        {pagedRows.map((row) => (
          <tr key={row.id} className={gridStyles.row}>
            <td className={gridStyles.strongCell}>{row.name}</td>
            <td className={`${gridStyles.monoCell} text-right`}>{row.cost}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
  <div className={gridStyles.pager}>
    <span className="text-gray-600">Showing 1-10 of 42 rows</span>
    <div className="flex items-center gap-2">
      <button className={gridStyles.pagerButton}>Previous</button>
      <span className="text-gray-700">Page 1 of 5</span>
      <button className={gridStyles.pagerButton}>Next</button>
    </div>
  </div>
</div>
```

### Audit Logging Skeleton

```python
from app.models.database import AuditLog

entry = AuditLog(
    user_id=current_user.user_id,
    user_email=current_user.email,
    action="update_page_configuration",
    resource_type="ui_page",
    resource_id=page_id,
    details={
        "page": "ExamplePage",
        "change": "updated filter defaults",
        "source": "ui_buddy_page_builder",
    },
    ip_address=request.client.host if request.client else None,
    status="success",
)
db.add(entry)
await db.commit()
```

### Backend Ollama Pattern

```python
# Follow the leadership_advisor_service pattern.
# Keep Ollama calls in backend services, not in the frontend.
# Use explicit schemas and safe fallbacks.
```

## Deliverables

When using this skill, the expected output should include:
- affected route and page/component list
- ATT compliance summary
- grid compliance summary for search and pagination
- audit logging decision: reused existing `audit_logs` only, or added explicit audit records
- Ollama decision: not needed, reused existing backend pattern, or added new backend-mediated AI endpoint
- validation results
- when helpful, a page scaffold derived from `.github/skills/ui-buddy-page-builder/templates/att-standard-page-template.tsx`

## Definition of Done

A page update is complete only when:
- the page visually matches ATT standards
- every grid has top-right search and bottom pagination
- shared UI primitives are reused where available
- audit tracking is accounted for through the existing audit model and middleware
- Ollama usage, if added, is backend-mediated and has a fallback
- the touched frontend and backend code paths validate successfully
