# Infra Alerts Page Audit

Date: 2026-03-15
Scope: frontend infra alerts grids
Overall compliance: 100%

## 2026-03-16 Performance Update

- Leadership dashboard and Amortized Cost page now use Redis page payload caching on top of existing DB-backed sources.
- Admin configuration `cache_ttl_seconds` is now applied as page cache TTL for leadership, amortized, advisor, forecast, and optimization summary payloads.
- Admin dashboard now exposes a `Release Cached Data` action that clears `pagecache:*` and `cost:*` keys.
- Backend validation passed with `uv run python -m compileall` over modified backend files.
- Frontend production build passed with `npm run build`; remaining note is a Vite chunk-size warning for the main bundle.

## 2026-03-16 Env Costs Grid Update

- Route `/env-costs` maps to `frontend/src/pages/AmortizedCostDashboard.tsx`.
- Standardized Service Breakdown, Subscription, Top Resources, Resource Type, Monthly Pivot, and Drill-down resources tables to use ATT shared grid chrome.
- Added a top-right search input and a bottom pagination bar to every grid on the page.
- Frontend validation passed for the updated page file and the frontend build completed successfully.

| Component | Search | Pagination | Sorting | Theme | Structure | Actions | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| VM Alerts | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| PG Alerts | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Expiry Alerts | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| VM Configurations | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Expiry Configurations | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Storage Configurations | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| PG Configurations | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Virtual Machines | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Storage Accounts | Pass | Pass | Pass | Pass | Pass | N/A | Pass |
| Managed Disks | Pass | Pass | Pass | Pass | Pass | N/A | Pass |
| PG Flexible Servers | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Notification History | Pass | Pass | Pass | Pass | Pass | N/A | Pass |

## 2026-03-17 Key Vault Audit History Update

- Reused the shared `audit_logs` table for explicit Key Vault business-event auditing on secret/key create, update, and delete operations.
- Added a backend `/api/v1/keyvault/history` endpoint that returns filtered CRUD history for the selected vault.
- Added a new Audit History tab on the Key Vault page with ATT grid styling, top search, filters, sorting, auto-refresh, and bottom pagination.
- Backend validation passed with `uv run python -m py_compile` and targeted pytest for `tests/test_keyvault_audit_history.py`.
- Frontend validation passed with `npx tsc --noEmit` and `npx vite build`; remaining note is the existing Vite chunk-size warning for the main bundle.

| Component | Search | Pagination | Sorting | Theme | Structure | Actions | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Key Vault Audit History | Pass | Pass | Pass | Pass | Pass | Pass | Pass |

## 2026-03-17 Admin CORS Settings Update

- Added an editable CORS origins form to the Admin dashboard configuration panel.
- Added DB-backed runtime CORS refresh in the backend so Admin-managed origins become effective without redeploy after the updated middleware is running.
- Backend validation passed with targeted py_compile and pytest coverage for CORS parsing and middleware refresh behavior.
- Frontend TypeScript validation passed for the Admin dashboard update.

| Component | Search | Pagination | Sorting | Theme | Structure | Actions | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Admin CORS Configuration | N/A | N/A | N/A | Pass | Pass | Pass | Pass |

## 2026-04-02 AKS CronJob Refresh Update

- Fixed the AKS Operations CronJobs grid so resume and suspend actions update the visible grid state immediately.
- Updated backend CronJob mutation handling to refresh the DB-backed CronJob cache after suspend, create, update, delete, and trigger operations.
- Fixed namespace-scoped CronJob sync so refreshing one namespace no longer wipes cached CronJobs for other namespaces in the same cluster.
- Frontend production build passed with `npm run build`; remaining note is the existing Vite chunk-size warning for the main bundle.

| Component | Search | Pagination | Sorting | Theme | Structure | Actions | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AKS CronJobs Grid | Pass | Pass | Pass | Pass | Pass | Pass | Pass |

## 2026-04-03 Leadership Dashboard Optimization Data Update

- Fixed orphaned snapshot detection so the optimization summary only flags snapshots whose source disk or snapshot no longer exists, instead of treating every snapshot older than 30 days as orphaned.
- Added a backend refresh path for the optimization summary and updated the Leadership Dashboard refresh button to refresh optimization summary data alongside the main leadership dashboard payload.
- Reviewed the other wastage buckets in the same service: unattached disks still use an explicit unattached-state query, idle resources still come from orphaned NIC detection plus advisor-driven recommendations, and overprovisioned resources remain advisor-driven.
- Frontend production build passed with `npm run build`; targeted backend pytest passed for the orphaned snapshot regression case.

| Component | Search | Pagination | Sorting | Theme | Structure | Actions | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Leadership Dashboard Wastage Summary | Pass | Pass | Pass | Pass | Pass | Pass | Pass |

## 2026-04-03 Env-Cost Resource Name Data Update

- Replaced blob-export CSV ingestion for amortized and env-cost data with Azure Cost Management API-only ingestion, keeping the UI DB-backed while removing Azure Blob export dependencies.
- Added detailed Cost Details API ingestion for amortized cost rows and normalized resource identifiers to the final resource segment so the env-cost drill-down grid shows actual resource names instead of synthetic `resource group / service` combinations.
- Removed the unused blob-cost service, deleted blob-export configuration fields, and removed the unused CSV-upload environment cost helper so there is no parallel blob/CSV cost ingestion path left in the backend.
- Added regression coverage for the API-only amortized sync path.
- Targeted backend pytest passed for the amortized sync regression suite.

| Component | Search | Pagination | Sorting | Theme | Structure | Actions | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Env-Cost Drilldown Resource Grid | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
