# Compliance Dashboard Fix v2 — Data Visibility + Performance

## Date: Session after compliance-cache-removal

## Problem 1: Empty Dashboard
- **Root cause:** `_resolve_scoped_subscription_ids()` returned `[]` when neither `admin_subscriptions` DB table nor `AZURE_SUBSCRIPTION_IDS` env-var was populated — causing the dashboard to short-circuit with `total_resources: 0`.
- **Fix:** Added `_discover_subscription_ids_from_data()` fallback that queries distinct subscription IDs from `SynapsePipelineChecksum` and `AKSPodChecksum` tables. Now the dashboard shows existing data even when no admin subscription scoping is configured.
- **File:** `backend/app/services/compliance_service.py` — `_resolve_scoped_subscription_ids()` method

## Problem 2: Slow Synapse/AKS/Schedules Pages
- **Root cause 1:** `_get_allowed_aks_cluster_names()` did unbounded `SELECT DISTINCT` on full `AKSPodChecksum` table.
- **Fix:** Added `WHERE snapshot_date >= 30 days ago` filter to bound the query.
- **Root cause 2:** No in-memory caching for AKS cluster names — called on every request.
- **Fix:** Added class-level `_aks_cluster_cache` with 5-minute TTL (same pattern as `_workspace_cache`).
- **Root cause 3:** Frontend `GRID_POLL_INTERVAL` was 30 seconds — too aggressive for heavy backend queries.
- **Fix:** Changed from 30s to 120s (2 minutes). Also replaced 3 hardcoded `30_000` refetchIntervals with the `GRID_POLL_INTERVAL` constant.
- **File (backend):** `backend/app/services/compliance_service.py`
- **File (frontend):** `frontend/src/services/complianceApi.ts`

## Verification
- `ruff format app/` — 72 files unchanged
- `ruff check app/` — all checks passed
- `pytest tests/` — 86 passed
- `tsc --noEmit` — exit 0, no errors
