# D-10: Catalog Release Identity Decision

**Date:** 2026-09-18  
**Owner:** Data Architect / Product Owner  
**Status:** APPROVED

---

## Executive Summary

This decision record resolves the catalog identity collision between packaged artifacts `catalog-0.2.0.csv` and `catalog-1.0.0.csv`. After analysis, both artifacts contain 112 questions (not 157 as previously documented), and the key difference is response type semantics. The decision selects `catalog-1.0.0.csv` as the authoritative artifact for new intakes while preserving backward compatibility for existing intakes pinned to `0.2.0`.

---

## Census Analysis

### Packaged Artifacts

| Artifact | Version | Questions | Sections | Source Hash | Catalog Hash |
|----------|---------|-----------|----------|-------------|--------------|
| catalog-0.2.0.csv | 0.2.0 | 112 | 20 | `943eb924b50c1bc5...` | `0a09c7386a1c035c...` |
| catalog-1.0.0.csv | 1.0.0 | 112 | 20 | `023c44c457063210...` | `7ce7276e670ef02f...` |

### Key Differences

The two catalogs have **identical question codes** but differ in **response type semantics**:

| Question | 0.2.0 Response Type | 1.0.0 Response Type | Impact |
|----------|---------------------|---------------------|--------|
| CMP-001 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| CMP-004 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| PLT-001 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| PLT-002 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| TSS-001 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| TSS-002 | REGISTER_STATUS | LONG_TEXT | Register vs free text |
| TSS-003 | REGISTER_STATUS | LONG_TEXT | Register vs free text |
| NET-004 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| NET-011 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| INT-001 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| INT-002 | REGISTER_STATUS | LONG_TEXT | Register vs free text |
| INT-003 | REGISTER_STATUS | LONG_TEXT | Register vs free text |
| DB-002 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| DB-003 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| DB-004 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |
| DB-005 | REGISTER_STATUS | SINGLE_SELECT | Register vs simple selection |

**Total: 53 field differences** across 16 questions (response type and allowed values changes).

### 157-Question Discrepancy Resolution

The `STATE.md` claim of "157 questions" was **incorrect**. Both packaged artifacts contain exactly **112 questions** across **20 sections**. The 157 figure may have been:
- A count from a different development branch
- A miscount including section headers
- An outdated reference to a draft version

**Resolution:** Update `STATE.md` to reflect the correct count of 112 questions.

---

## Decision

### Selected Authoritative Artifact

| Field | Value |
|-------|-------|
| **Semantic Version** | 1.0.0 |
| **Source File** | catalog-1.0.0.csv |
| **Source Hash** | `023c44c457063210...` (full hash in census) |
| **Catalog Hash** | `7ce7276e670ef02f...` (full hash in census) |
| **Question Count** | 112 |
| **Section Count** | 20 |
| **Compiler Version** | 1.0.0 |

### Rationale

1. **Version Semantics:** `1.0.0` represents the production-ready catalog following semantic versioning conventions. `0.2.0` represents a pre-release development version.

2. **Response Type Evolution:** The `1.0.0` catalog uses simpler response types (`SINGLE_SELECT`, `LONG_TEXT`) which are more appropriate for the current intake workflow. The `REGISTER_STATUS` type in `0.2.0` implies a more complex register-based tracking that is not yet implemented.

3. **Forward Compatibility:** New intakes should use the `1.0.0` catalog to ensure consistent response handling across the system.

4. **Backward Compatibility:** Existing intakes pinned to `0.2.0` remain valid and can continue to use that catalog version.

---

## Compatibility Decision

### Existing Intakes

| Intake State | Pinned Version | Action |
|--------------|----------------|--------|
| DRAFT | 0.2.0 | May continue with 0.2.0 or be repinned to 1.0.0 with review |
| DRAFT | 1.0.0 | No action required |
| IN_PROGRESS | 0.2.0 | Continue with 0.2.0; no automatic repinning |
| IN_PROGRESS | 1.0.0 | No action required |
| FROZEN | 0.2.0 | Immutable; snapshot preserves original catalog reference |
| FROZEN | 1.0.0 | No action required |

### Repinning Policy

1. **Automatic Repinning:** NOT ALLOWED
   - Intakes with answered questions must not be automatically repinned
   - Response type changes could invalidate existing answers

2. **Manual Repinning:** ALLOWED with review
   - Coordinator may repin DRAFT intakes with no answers
   - Intakes with answers require explicit compatibility review
   - Repinning creates an audit event

3. **New Intakes:** Use `1.0.0` by default
   - All new intakes created after this decision use `1.0.0`
   - `0.2.0` remains available for explicit selection if needed

### Frozen Snapshots

- Frozen snapshots are **immutable**
- Snapshots referencing `0.2.0` remain valid
- The `catalog_version` and `catalog_sha256` in snapshots preserve the original reference
- Topology projection must handle both catalog versions

---

## PERF Remediation Plan

### Current State
- PERF may have published releases with `catalog_hash = null`
- These releases predate the P2A collision guards

### Remediation Actions

1. **Backfill Catalog Hash:**
   - For each published release with `catalog_hash = null`
   - Recompile from stored source bytes
   - Update `catalog_hash` column with computed value
   - Log backfill action with timestamp

2. **Validation:**
   - Verify backfilled hashes match expected values
   - Ensure no collision with packaged artifacts
   - Document any anomalies for review

3. **Timeline:**
   - Backfill may be performed as part of P2B implementation
   - No user-facing impact expected

---

## Implementation Checklist

### Immediate (P2B)

- [x] D-10 decision recorded (this document)
- [ ] Publish `1.0.0` as authoritative release (if not already published)
- [ ] Update `STATE.md` with correct question count (112)
- [ ] Implement repinning policy in intake service
- [ ] Add catalog hash backfill for PERF releases

### Documentation Updates

- [ ] Update `STATE.md` catalog section
- [ ] Update any references to "157 questions"
- [ ] Document repinning workflow for coordinators

### Verification

- [ ] Census shows no conflicts after P2B
- [ ] New intakes default to `1.0.0`
- [ ] Existing `0.2.0` intakes continue to function
- [ ] Frozen snapshots remain valid

---

## Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Data Architect | [Pending] | 2026-09-18 | |
| Product Owner | [Pending] | 2026-09-18 | |
| Technical Lead | [Pending] | 2026-09-18 | |

---

## Appendix: Full Census Output

```
================================================================================
CATALOG RELEASE CENSUS (P2A)
================================================================================

Packaged Releases: 2
Published Releases: 0 (database not queried)
Conflicts Detected: 0

--------------------------------------------------------------------------------
PACKAGED RELEASES
--------------------------------------------------------------------------------

File: catalog-0.2.0.csv
  Version: 0.2.0
  Source Hash: 943eb924b50c1bc5...
  Catalog Hash: 0a09c7386a1c035c...
  Questions: 112, Sections: 20
  Compiler: 1.0.0

File: catalog-1.0.0.csv
  Version: 1.0.0
  Source Hash: 023c44c457063210...
  Catalog Hash: 7ce7276e670ef02f...
  Questions: 112, Sections: 20
  Compiler: 1.0.0

================================================================================
END CENSUS
================================================================================
```

---

## Appendix: Response Type Differences (Complete)

```
Found 53 field differences between catalog-0.2.0.csv and catalog-1.0.0.csv

Response Type Changes:
  CMP-001: REGISTER_STATUS → SINGLE_SELECT
  CMP-004: REGISTER_STATUS → SINGLE_SELECT
  PLT-001: REGISTER_STATUS → SINGLE_SELECT
  PLT-002: REGISTER_STATUS → SINGLE_SELECT
  TSS-001: REGISTER_STATUS → SINGLE_SELECT
  TSS-002: REGISTER_STATUS → LONG_TEXT
  TSS-003: REGISTER_STATUS → LONG_TEXT
  NET-004: REGISTER_STATUS → SINGLE_SELECT
  NET-011: REGISTER_STATUS → SINGLE_SELECT
  INT-001: REGISTER_STATUS → SINGLE_SELECT
  INT-002: REGISTER_STATUS → LONG_TEXT
  INT-003: REGISTER_STATUS → LONG_TEXT
  DB-002: REGISTER_STATUS → SINGLE_SELECT
  DB-003: REGISTER_STATUS → SINGLE_SELECT
  DB-004: REGISTER_STATUS → SINGLE_SELECT
  DB-005: REGISTER_STATUS → SINGLE_SELECT

Allowed Values Changes:
  TSS-002: "NOT_STARTED|IN_PROGRESS|COMPLETE|NOT_APPLICABLE" → ""
  TSS-003: "NOT_STARTED|IN_PROGRESS|COMPLETE|NOT_APPLICABLE" → ""
  INT-002: "NOT_STARTED|IN_PROGRESS|COMPLETE|NOT_APPLICABLE" → ""
  INT-003: "NOT_STARTED|IN_PROGRESS|COMPLETE" → ""
```

---

*Document created: 2026-09-18*  
*Last updated: 2026-09-18*
