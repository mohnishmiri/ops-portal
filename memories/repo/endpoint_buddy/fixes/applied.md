# Applied Fixes

## 2026-03-14 — Compliance Excel Export & Schedule Detail Fixes

### Fix 1: Checksum Schedule Detail 404
- **Endpoint**: GET /api/v1/checksum-schedules/{schedule_id}
- **Root Cause**: `get_checksum_schedule(schedule_id: str)` passed string to integer PK column in DB query
- **File**: `backend/app/services/compliance_service.py`
- **Change**: Added `_normalize_schedule_id(schedule_id: str) -> int` to convert before query
- **Status**: ✅ Live-verified returning 200

### Fix 2: Excel Export 500 — Enum Casing
- **Endpoint**: GET /api/v1/compliance/export/excel
- **Root Cause**: `ModuleType.synapse` (lowercase) should be `ModuleType.SYNAPSE`
- **File**: `backend/app/services/compliance_excel_service.py`
- **Change**: Corrected all enum references to uppercase
- **Status**: ✅ Prerequisite fix

### Fix 3: Excel Export 500 — String datetime in _fmt_dt
- **Endpoint**: GET /api/v1/compliance/export/excel
- **Root Cause**: `_fmt_dt()` called `.strftime()` on string values from DB varchar columns
- **File**: `backend/app/services/compliance_excel_service.py`
- **Change**: Updated `_fmt_dt` and `_fmt_date` to accept `str | datetime | None`; strings returned as-is
- **Status**: ✅ Confirmed working

### Fix 4: Excel Export 500 — ExportMetadata Missing Fields
- **Endpoint**: GET /api/v1/compliance/export/excel
- **Root Cause**: Endpoint accessed `metadata.sheet_names` and `metadata.file_size_bytes` but ExportMetadata schema lacked those fields
- **Files**: `backend/app/schemas/compliance.py`, `backend/app/services/compliance_excel_service.py`
- **Change**: Added `sheet_names: list[str]` and `file_size_bytes: int` to ExportMetadata; populated from `wb.sheetnames` and `buf.getbuffer().nbytes`
- **Status**: ✅ Live-verified: HTTP 200, 4 sheets, 96,425 rows, 135s response time

### Fix 5: openpyxl Illegal Characters Sanitization
- **Endpoint**: GET /api/v1/compliance/export/excel  
- **Root Cause**: Some DB string values contain XML control characters that openpyxl rejects
- **File**: `backend/app/services/compliance_excel_service.py`
- **Change**: Added `ILLEGAL_CHARACTERS_RE.sub('', value)` before writing each string cell
- **Status**: ✅ Applied (preventive)

### Dev Environment Fix
- **Issue**: pytest not installed in `.venv`
- **Fix**: `uv sync --extra dev --native-tls` in background terminal to avoid interruption
- **Regression Tests**: `tests/test_compliance_regressions.py` — 4 PASSED in 57.20s
