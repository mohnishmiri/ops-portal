# Compliance Module — Cache Removal & Permanent Fix

**Date:** 2025-session
**Issue:** Compliance Dashboard showing "No compliance data available" and "Score recalculation failed" toast repeatedly across multiple sessions.

## Root Causes Identified

1. **Dashboard endpoint served stale/empty DB snapshots** — `GET /dashboard` checked `ComplianceDashboardSnapshot` cache first. If snapshot was empty (from a failed sync), it returned zeros → frontend showed empty state.
2. **Calculate endpoint returned `{"error": "..."}` as HTTP 200** — When no monitored subscriptions configured, `_calculate_all_compliance_scores` returned an error dict, not an HTTP error. Frontend treated 200 as success, invalidated dashboard (still empty), showed empty state.
3. **No error handling on endpoints** — Unhandled exceptions propagated as 500s. Frontend mutation's `onError` fired → "Score recalculation failed" toast.
4. **`DefaultAzureCredential()` could crash service init** — If Azure creds not available, entire endpoint failed.
5. **Redis caching stored empty payloads** — After a failed sync, Redis cached empty results, subsequent requests got empty data.

## Changes Made

### Backend `compliance.py` (endpoints):
- **Removed DB snapshot cache** from `GET /dashboard` — always computes live
- **Removed `schedule_background_sync`** from calculate and dashboard endpoints
- **Added try/except** with proper `HTTPException` responses on both endpoints
- **Added check** for `{"error": ...}` dict — raises HTTP 400 instead of returning as 200

### Backend `compliance_service.py`:
- **`__init__`**: Wrapped `DefaultAzureCredential()` in try/except — sets `self.credential = None` if it fails
- **`_calculate_all_compliance_scores`**: Returns valid empty structure (not `{"error": ...}`) when no subscriptions
- **`get_compliance_dashboard`**: Added early return with valid empty dashboard when no subscriptions configured

### Backend `compliance_sync_service.py`:
- **Removed Redis cache writes** from `full_sync()` — only invalidates (no `set_cached`)
- **Removed unused import** of `get_effective_cache_ttl_seconds` and `get_redis_enabled`

### Frontend `complianceApi.ts`:
- **Simplified `refreshComplianceDashboard`** — just invalidates queries (no `removeQueries` + `prefetchQuery` with `refresh=true`)

### Frontend `ComplianceDashboard.tsx`:
- **Fixed empty state check** — now checks `total_resources > 0` in addition to `dashboardData` being truthy. Prevents showing dashboard with all zeros.

## Key Principle
The compliance module now operates cache-free: always live data, proper error propagation, no stale snapshots. The `/dashboard/sync` admin endpoint still exists for historical data collection but is not in the hot path.
