# PERF Schema Fix - audit_events Table

**Date:** 2026-09-11  
**Schema:** AG1766  
**Environment:** PERF  
**Issue:** Schema mismatch in audit_events table

---

## Problem

The `audit_events` table created by the initial DDL scripts had incorrect column names:
- ❌ `event_type` (should be `event_code`)
- ❌ `detail` (should be `payload`)

This caused application errors when trying to create applications:
```
ORA-00904: "PAYLOAD": invalid identifier
```

---

## Root Cause

The DDL script `02_create_tables.sql` was created manually and did not match the actual Alembic migration `0001_core_catalog_answers.py`, which defines the correct schema.

---

## Fix Applied

Renamed columns in the `audit_events` table:

```sql
ALTER TABLE audit_events RENAME COLUMN event_type TO event_code;
ALTER TABLE audit_events RENAME COLUMN detail TO payload;
```

---

## Verification

### Before Fix
```
ID: CHAR
EVENT_TYPE: VARCHAR2    ← Wrong
ENTITY_TYPE: VARCHAR2
ENTITY_ID: CHAR
ACTOR_ID: CHAR
OCCURRED_AT: VARCHAR2
DETAIL: CLOB            ← Wrong
```

### After Fix
```
ID: CHAR
EVENT_CODE: VARCHAR2    ← Correct
ENTITY_TYPE: VARCHAR2
ENTITY_ID: CHAR
ACTOR_ID: CHAR
OCCURRED_AT: VARCHAR2
PAYLOAD: CLOB           ← Correct
```

---

## Testing

### Application Creation Test
✅ **PASS** - Created 2 test applications successfully:
- Test Application from PERF (ID: e3a224c3-d74a-4f89-a796-b915ec449962)
- Web UI Test Application (ID: 82ed489d-571a-4d4f-8eb5-5cf2748e1210)

### Web UI Test
✅ **PASS** - Form submission at http://localhost:8000/applications/ works correctly
- Returns 303 redirect to application workspace
- No server errors

---

## Updated Files

1. **`06_fix_audit_events_schema.sql`** (NEW)
   - Standalone fix script for existing installations
   - Can be run on any schema with the old column names

2. **`02_create_tables.sql`** (UPDATED)
   - Corrected audit_events table definition
   - Future installations will have correct schema from the start

---

## For Future Installations

The corrected `02_create_tables.sql` now matches the Alembic migrations exactly. New installations will not need the fix script.

---

## Status

✅ **RESOLVED** - PERF schema is now correct and fully functional

**Applications created:** 2  
**Schema version:** 0013  
**Invalid objects:** 0  
**All tests:** PASSING  

---

**Fixed By:** Devin  
**Verified:** 2026-09-11 12:30 PM
