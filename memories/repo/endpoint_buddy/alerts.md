# Current Alerts

- GET /api/v1/compliance/export/excel:aks_checksum_download (GET /api/v1/compliance/checksum-runs/{id}/download) — 404 for AKS run IDs when no CSV results exist in DB, may be a data issue.
- Local shell requests using localhost can be intercepted by a corporate loopback proxy; use 127.0.0.1 for reliable local testing.

## Resolved (2026-03-14)

- ✅ GET /api/v1/checksum-schedules/{schedule_id} 404 — FIXED: `_normalize_schedule_id()` converts string ID to int before DB query
- ✅ GET /api/v1/compliance/export/excel 500 — FIXED: three-layer fix: (1) ModuleType enum casing, (2) _fmt_dt handles str|datetime inputs, (3) ExportMetadata missing sheet_names/file_size_bytes fields
