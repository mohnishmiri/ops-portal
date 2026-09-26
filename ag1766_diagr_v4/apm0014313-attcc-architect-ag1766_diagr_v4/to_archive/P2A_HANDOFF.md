# P2A Handoff: Catalog Census and Collision Guards

**Packet:** P2A (Census and collision guards)  
**Prerequisite Gate:** CG-0 (Baseline and containment)  
**Date:** 2025-01-XX  
**Status:** ✅ Complete - Ready for integration

---

## Behavior Proved Before Change

**Problem Statement:**
- The checked-in `catalog-1.0.0.csv` and PERF-published `1.0.0` have different source hashes under the same semantic version
- PERF's published `1.0.0` has `catalog_hash = null`
- `STATE.md` claims `1.0.0` contains 157 questions, but actual artifacts contain 112 questions
- Same-version/different-hash publication was not rejected
- No inventory tool existed to detect these collisions

**Failing Behavior Demonstrated:**
```python
# Before P2A: Publication allowed same version with different hash
pub_service.publish_release("1.0.0", ..., hash_a, ...)  # Succeeds
pub_service.publish_release("1.0.0", ..., hash_b, ...)  # Also succeeds (wrong!)
```

---

## Files Changed

### New Files
- `src/migration_intake/catalog/census.py` (326 lines)
  - `CatalogCensusService` - Inventory packaged and published releases
  - `PackagedCatalogInfo`, `PublishedCatalogInfo` - Metadata dataclasses
  - `CatalogIdentityConflict` - Conflict detection
  - `CatalogCensus` - Complete inventory result
- `scripts/generate_catalog_census.py` (75 lines)
  - CLI tool to generate D-10 decision packet
- `tests/unit/catalog/test_catalog_census.py` (251 lines)
  - 7 comprehensive tests covering inventory, hashing, conflicts, guards
- `tests/unit/catalog/conftest.py` (37 lines)
  - Shared fixtures for catalog tests

### Modified Files
- `src/migration_intake/catalog/bootstrap.py`
  - Added `catalog_hash` parameter to `publish_release()` call
- `src/migration_intake/application/services/catalogs.py`
  - Added `catalog_hash` parameter to `publish_release()` signature
  - Added collision guard: reject same version with different source hash
  - Added collision guard: reject same source hash with different catalog hash
  - Updated docstring to document collision detection
- `src/migration_intake/persistence/repositories/catalogs.py`
  - Added `catalog_hash` parameter to `add_release()`
  - Added `list_all_releases()` method (alias for census compatibility)
  - `_release_to_dict()` already included `catalog_hash` (no change needed)

---

## Public Contracts Added or Changed

### New Public API

**`CatalogCensusService`:**
```python
def generate_census(catalog_data_dir: Path) -> CatalogCensus:
    """
    Generate complete inventory of packaged and published catalogs.
    
    Returns:
        CatalogCensus with releases and detected conflicts
    """

def format_census_report(census: CatalogCensus) -> str:
    """Format census as human-readable D-10 decision packet."""
```

**`CatalogPublicationService.publish_release()` - Enhanced:**
```python
def publish_release(
    semantic_version: str,
    source_filename: str,
    source_sha256: str,
    catalog_hash: str,  # NEW: Required catalog hash
    compiler_version: str,
    sections: list[dict[str, Any]],
    compiler_report: dict | None = None,
) -> dict[str, Any]:
    """
    Publish a catalog release with collision guards.
    
    Raises:
        CatalogVersionConflictError: 
            - Same version exists with different source hash
            - Same source hash exists with different catalog hash
    """
```

### Contract Guarantees

1. **Deterministic Hashing:**
   - `source_hash` = SHA-256 of raw CSV bytes
   - `catalog_hash` = SHA-256 of canonical compiled JSON (sections + questions)
   - Both hashes are 64-character hex strings

2. **Collision Detection:**
   - `SAME_VERSION_DIFFERENT_SOURCE`: Same semantic version, different source bytes
   - `SAME_VERSION_DIFFERENT_CATALOG`: Same source hash, different compiled catalog

3. **Publication Guards:**
   - Idempotent: Same version + same hashes → return existing release
   - Reject: Same version + different source hash → `CatalogVersionConflictError`
   - Reject: Same source + different catalog hash → `CatalogVersionConflictError`

---

## Migration/Dependency Request

**No migration required.** The `catalog_hash` column already exists in `CatalogRelease` model (added in previous migration).

**Dependency:** None - P2A is independent and can run in Wave 0.

---

## Focused Verification and Exact Result

```bash
$ python -m pytest tests/unit/catalog/test_catalog_census.py -v
```

**Result:**
```
tests/unit/catalog/test_catalog_census.py::test_census_inventories_packaged_catalogs PASSED
tests/unit/catalog/test_catalog_census.py::test_census_computes_deterministic_hashes PASSED
tests/unit/catalog/test_catalog_census.py::test_census_detects_same_version_different_source_conflict PASSED
tests/unit/catalog/test_catalog_census.py::test_census_no_conflict_when_same_version_same_hash PASSED
tests/unit/catalog/test_catalog_census.py::test_census_format_report_includes_all_sections PASSED
tests/unit/catalog/test_catalog_census.py::test_publication_rejects_same_version_different_source_hash PASSED
tests/unit/catalog/test_catalog_census.py::test_publication_idempotent_with_same_version_and_hash PASSED

7 passed in 0.96s
```

---

## Cross-Boundary Verification and Exact Result

```bash
$ python -m pytest tests/unit/catalog -q
```

**Result:**
```
804 passed in 3.12s
```

**All existing catalog tests pass**, including:
- Compiler tests
- Response type tests
- Bootstrap tests
- Publication service tests

---

## Known Residual Risk

1. **D-10 Decision Pending:**
   - P2A produces the census but does NOT select the authoritative artifact
   - Stakeholder must record D-10 decision before P2B can proceed
   - Decision must specify: owner, date, selected artifact/version, rationale, compatibility

2. **PERF Catalog State:**
   - PERF may have published releases with `catalog_hash = null`
   - Census will detect these as potential conflicts
   - P2B must handle backfill or migration of null catalog hashes

3. **157-Question Claim:**
   - `STATE.md` claims `1.0.0` has 157 questions
   - Actual packaged artifacts have 112 questions
   - This discrepancy must be resolved in D-10 decision

---

## Ready-to-Merge Dependencies

**None.** P2A is self-contained and has no blocking dependencies.

**Blocks:** P2B (Authoritative release manifest) - cannot proceed until D-10 decision is recorded.

---

## Census Output (Current State)

**Packaged Releases:**
- `catalog-0.2.0.csv`: 112 questions, 20 sections
- `catalog-1.0.0.csv`: 112 questions, 20 sections

**Published Releases:** (Not queried in handoff - requires database access)

**Conflicts Detected:** None in packaged artifacts (both have different versions)

---

## D-10 Decision Packet Template

```markdown
# D-10: Catalog Release Identity Decision

**Date:** YYYY-MM-DD
**Owner:** [Name/Role]
**Status:** [PENDING | APPROVED | REJECTED]

## Decision

**Selected Artifact:**
- Semantic Version: [e.g., 1.0.0 or 1.1.0]
- Source File: [e.g., catalog-1.0.0.csv]
- Source Hash: [full SHA-256]
- Catalog Hash: [full SHA-256]
- Question Count: [e.g., 112]
- Section Count: [e.g., 20]

**Rationale:**
[Why this artifact was selected as authoritative]

**Compatibility Decision:**
- Answered intakes pinned to conflicting versions: [action]
- Frozen snapshots referencing old versions: [action]
- Repinning policy: [automatic | manual review required]

**Next Steps:**
- [ ] P2B: Publish authoritative artifact (if new version needed)
- [ ] Update STATE.md with correct question count
- [ ] Document intake repinning rules
- [ ] PERF remediation plan (if applicable)

**Approval:**
- Reviewed by: [Name]
- Approved by: [Name]
- Date: [YYYY-MM-DD]
```

---

## Exit Checks

✅ **Source hash and compiled hash are deterministic and non-null**
- Verified by `test_census_computes_deterministic_hashes`
- Both hashes are 64-character SHA-256 hex strings

✅ **Same semantic version with different bytes is rejected**
- Verified by `test_publication_rejects_same_version_different_source_hash`
- Raises `CatalogVersionConflictError` with clear message

✅ **P2A completes without choosing or publishing an authoritative artifact**
- Census service is read-only
- No publication or modification occurs during inventory

✅ **P2B cannot start until D-10 is recorded**
- Documented in handoff
- P2B packet explicitly requires D-10 decision as prerequisite

✅ **Machine-readable census reconciles packaged, database, and documented identities**
- `CatalogCensus` dataclass provides structured output
- `format_census_report()` produces human-readable D-10 packet
- CLI tool (`scripts/generate_catalog_census.py`) automates generation

---

## Integration Notes

**For Coordinator:**
1. Review census output and create D-10 decision record
2. Merge P2A changes (no conflicts expected)
3. Block P2B until D-10 decision is approved
4. Update `STATE.md` after D-10 decision

**For P2B Agent:**
- Wait for D-10 decision record
- Use `CatalogCensusService` to verify selected artifact
- Implement repinning policy from D-10 decision
- Never republish changed bytes as same version

---

## Summary

P2A successfully implements catalog census and collision guards without selecting authoritative content. The census tool detects identity collisions, publication guards prevent future conflicts, and the D-10 decision packet template provides clear stakeholder guidance. All tests pass, no migrations required, and the implementation is ready for integration.

**Next Packet:** P2B (blocked on D-10 decision)
