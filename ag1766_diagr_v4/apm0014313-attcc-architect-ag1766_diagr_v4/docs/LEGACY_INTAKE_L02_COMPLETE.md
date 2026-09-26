# Legacy Intake Workbook Import — L02 Complete

**Date:** 2026-09-11  
**Slice:** L02 — Persistence and Oracle Migration  
**Status:** ✅ **COMPLETE**

---

## Summary

Slice L02 adds the persistence layer for legacy intake workbook import:
- New `import_lane` column to distinguish upload lanes
- New `matched_identifier_type` column to record which ID type was used
- New `base_answer_revision` column for stale-answer detection
- Migration 0013 tested and verified on both SQLite and Oracle

---

## Files Created/Modified

### Migration

1. **`src/migration_intake/persistence/migrations/versions/0013_legacy_intake_support.py`** (90 lines)
   - Adds `import_lane` to `import_runs` (SOURCE_DOCUMENT, GAP_WORKBOOK, LEGACY_INTAKE)
   - Adds `matched_identifier_type` to `import_runs` (CORRELATION, MOTS, ITAP)
   - Adds `base_answer_revision` to `candidates`
   - Backfills existing rows with `SOURCE_DOCUMENT` lane
   - Idempotent: checks for existing columns before adding

### ORM Models

2. **`src/migration_intake/persistence/models_imports.py`** (modified)
   - Added `import_lane: Any = Column(String(30), nullable=True)`
   - Added `matched_identifier_type: Any = Column(String(20), nullable=True)`

3. **`src/migration_intake/persistence/models_candidates.py`** (modified)
   - Added `base_answer_revision: Any = Column(Integer(), nullable=True)`
   - Comment: "Stale-answer detection (for legacy intake imports)"

---

## Schema Changes

### import_runs Table

| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `import_lane` | String(30) | Yes | Distinguishes upload lanes: SOURCE_DOCUMENT, GAP_WORKBOOK, LEGACY_INTAKE |
| `matched_identifier_type` | String(20) | Yes | Records which ID type was used for matching: CORRELATION, MOTS, ITAP |

**Existing rows:** Backfilled with `import_lane = 'SOURCE_DOCUMENT'`

### candidates Table

| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `base_answer_revision` | Integer | Yes | Answer revision number at import time (for stale-answer detection) |

**Usage:** When a legacy intake candidate is created, capture the current answer revision. At acceptance time, compare against the current revision to detect if the answer changed since import.

---

## Migration Test Results

### SQLite

```
INFO  [alembic.runtime.migration] Running upgrade 0012 -> 0013, Add legacy intake workbook import support.
✅ Migration successful on SQLite

import_runs columns: [..., 'import_lane', 'matched_identifier_type', ...]
candidates columns: [..., 'base_answer_revision', ...]
✅ All new columns present
```

### Oracle

```
INFO  [alembic.runtime.migration] Running upgrade 0012 -> 0013, Add legacy intake workbook import support.
Migration successful on Oracle

import_runs has 20 columns
candidates has 26 columns
All new columns verified on Oracle
```

---

## Import Lane Values

The `import_lane` column supports three distinct upload paths:

1. **SOURCE_DOCUMENT**
   - UAQ (Unified Application Questionnaire)
   - Interface Tracking
   - WaveUtil
   - These are source documents with strict identity gates

2. **GAP_WORKBOOK**
   - Generated intake forms with embedded application/intake IDs
   - Used for completing missing answers
   - Has concurrency tokens

3. **LEGACY_INTAKE** (new)
   - Seven-sheet App Data Capture workbooks
   - Completed intake forms from legacy process
   - No embedded IDs or concurrency tokens
   - Requires identity resolution and intake selection

---

## Matched Identifier Type Values

The `matched_identifier_type` column records which external ID was used for application matching:

- **CORRELATION** — Correlation ID (highest precedence)
- **MOTS** — MOTS ID (fallback if Correlation absent)
- **ITAP** — iTAP/APM ID (fallback if both higher-priority IDs absent)
- **NULL** — No identifier-based matching (e.g., gap workbooks with embedded app ID)

---

## Base Answer Revision Usage

The `base_answer_revision` field enables stale-answer detection for legacy intake imports:

### At Import Time

```python
# When creating a candidate from legacy intake
current_answer = get_current_answer(intake_id, question_code)
candidate = Candidate(
    ...
    base_answer_revision=current_answer.revision if current_answer else None,
)
```

### At Acceptance Time

```python
# Before accepting the candidate
current_answer = get_current_answer(intake_id, question_code)
if candidate.base_answer_revision is not None:
    if current_answer and current_answer.revision != candidate.base_answer_revision:
        # Answer changed since import — block acceptance
        raise AnswerChangedSinceImportError(
            expected_revision=candidate.base_answer_revision,
            current_revision=current_answer.revision,
        )
```

### Bulk Acceptance

For bulk operations, stale candidates can be:
- Skipped with a warning
- Reported separately
- Accepted only if unchanged

---

## Database Compatibility

Both SQLite and Oracle support:
- ✅ String(30) for `import_lane`
- ✅ String(20) for `matched_identifier_type`
- ✅ Integer for `base_answer_revision`
- ✅ Nullable columns
- ✅ Batch alter table operations
- ✅ UPDATE statements for backfill

---

## Verification

### Run Migration

```bash
# SQLite
DATABASE_URL="sqlite:///test.db" python -m alembic upgrade head

# Oracle
DATABASE_URL="oracle+oracledb://user:pass@host:port?service_name=service" python -m alembic upgrade head
```

### Verify Columns

```python
from sqlalchemy import create_engine, inspect

engine = create_engine(DATABASE_URL)
inspector = inspect(engine)

# Check import_runs
import_runs_cols = {col['name'] for col in inspector.get_columns('import_runs')}
assert 'import_lane' in import_runs_cols
assert 'matched_identifier_type' in import_runs_cols

# Check candidates
candidates_cols = {col['name'] for col in inspector.get_columns('candidates')}
assert 'base_answer_revision' in candidates_cols
```

---

## Next Steps

### L03 — Upload and Intake-Selection UX

1. Add third lane card on Sources page ("Legacy Completed Intake")
2. Create upload route `/sources/legacy-intake/upload`
3. Implement identity extraction and resolution
4. Create identity result screen (MATCHED, MISSING, MISMATCH, AMBIGUOUS, CONFLICT)
5. Create intake chooser screen (show eligible intakes for matched application)
6. Web integration tests

### L04 — Reviewed Legacy Mapping

1. Define exact field mappings for App, iTAP, TSS, Provisioning sheets
2. Create versioned mapping artifact
3. Implement deterministic parsing
4. Create findings for unknown fields
5. Mapping and service tests

### L05 — Stale-Answer Protection

1. Capture baseline revision at import
2. Check baseline at acceptance
3. Block stale overwrites
4. Mixed bulk outcomes
5. Conflict UI

### L06 — End-to-End Gate

1. Browser journey
2. SQLite regression
3. Oracle verification
4. Documentation

---

**Status:** ✅ **L02 COMPLETE** — Ready for L03 (Upload and Intake-Selection UX)
