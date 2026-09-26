# Catalog Release Manifest

**Version:** 1.0.0  
**Last Updated:** 2026-09-18  
**Decision Reference:** D-10_CATALOG_DECISION_RECORD.md

---

## Authoritative Release

| Field | Value |
|-------|-------|
| **Semantic Version** | 1.0.0 |
| **Source File** | catalog-1.0.0.csv |
| **Source SHA-256** | `023c44c457063210...` (computed at compile time) |
| **Catalog SHA-256** | `7ce7276e670ef02f...` (computed at compile time) |
| **Question Count** | 112 |
| **Section Count** | 20 |
| **Compiler Version** | 1.0.0 |

---

## Release History

| Version | Status | Questions | Sections | Notes |
|---------|--------|-----------|----------|-------|
| 1.0.0 | AUTHORITATIVE | 112 | 20 | Production catalog per D-10 |
| 0.2.0 | LEGACY | 112 | 20 | Pre-release; existing intakes may reference |

---

## Compatibility Policy

### New Intakes
- All new intakes MUST use version `1.0.0`
- Bootstrap automatically publishes `1.0.0` on first boot

### Existing Intakes
- Intakes pinned to `0.2.0` remain valid
- No automatic repinning is performed
- Manual repinning requires explicit review

### Frozen Snapshots
- Frozen snapshots are immutable
- Snapshots preserve their original catalog reference
- Topology projection handles both versions

---

## Verification

To verify the authoritative release:

```bash
# Generate census and verify hashes
python -m migration_intake.catalog.census

# Verify bootstrap points to correct artifact
python -c "from migration_intake.catalog.bootstrap import CATALOG_VERSION, CATALOG_FILENAME; print(f'{CATALOG_VERSION}: {CATALOG_FILENAME}')"
```

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-09-18 | Initial manifest created per D-10 decision | System |
