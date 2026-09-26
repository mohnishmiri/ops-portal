# CCPM test-only application profile

**Profile:** `CCPM_TEST_LABEL_ONLY`, version `0.1.0`, capability `LABEL_ONLY`.

This is a bounded test definition, not a production AWS topology mapping. It is
kept outside the packaged profile registry and is **not selectable through the
current web UI**. Load it explicitly with `load_profile_from_path`, or with
`load_test_profile()` from [the preparation utility](../../../scripts/ccpm_test_profile.py).
No approved-by metadata is fabricated. Official generation stays disabled.

## Binding and preservation contract

The selected application diagram has two existing pages but no approved label
targets. Rather than infer the meaning of private cells, preparation appends a
third page named **CCPM Test Controls** to a new in-memory/derived base.

| Slot | Canonical source | Selector | Projection property | Target |
|---|---|---|---|---|
| CCPM_TEST_NAME | Confirmed CTL-002 TEXT_PAIR | TEXT_PAIR.first | application.name | APPLICATION_NAME marker on test page |
| CCPM_TEST_ACRONYM | Confirmed CTL-002 TEXT_PAIR | TEXT_PAIR.second | application.acronym | APPLICATION_ACRONYM marker on test page |

Both slots require exactly one match. There are no defaults or inferred values.
Use `fact_mappings()` with the existing strict v3 projection boundary. Persist
and verify the resulting projection before governed rendering; do not reread live
answers during rendering. Synthetic tests verify that missing/unconfirmed facts
cannot render successfully.

- The new page carries **TEST ONLY - NOT AN APPROVED TOPOLOGY**.
- The original two pages have **no assigned environment/site meaning**. The test
  uses an explicit synthetic TEST/SYNTHETIC_SITE context only.
- Only the two label values on the new page may change during rendering.
- Existing topology nodes, edges, geometry, styles, parents and labels are protected.
- No VPC, subnet, compute, storage or interface is inferred or generated.
- Preparation is a separate operation, not a STRUCTURAL generation claim.
- Existing bounded-parser normalization assigns deterministic IDs to recognized
  empty ID-less placeholders. XML serialization may also change byte formatting.
  Therefore compare protected pages after that normalization, not raw file bytes.
  Always retain the original byte hash separately from the derived base hash.

## Local preparation

Use the supported Python 3.13 interpreter. The selected source must be an
uncompressed two-page Draw.io file inside this workspace with an explicitly
supplied expected SHA-256. No workbook or database is read by this utility.

From the workspace root, this command is **dry-run only**:

```powershell
& 'H:\Tools\Python313Embedded\python.exe' -B scripts/ccpm_test_profile.py `
  --source 'docs/architecture/CCPM_18678_TargetState_AWS_OutPosts_v01 (1).drawio' `
  --expected-sha256 3df0f756a748277a6cc7d32abffdba8737ee463dcf7dc913cba721e89d0dc8af
```

It reports only profile/source/derived digests, byte count and page counts. It
does not emit XML, labels, images or source values. If the source changes, stop
and review the new identity rather than silently replacing the expected digest.

If retention of a private derivative is authorized, supply **both** `--write`
and `--output` with a new file in an approved ignored directory inside the
workspace. The parent directory must exist. Existing files, source overwrite,
outside-workspace paths, symlinks, junctions and reparse components are refused.
The CLI is for a trusted local workspace, not a hostile multi-user filesystem.
Never commit the original or derived private evidence, copy it outside this
workspace, or use it as a committed automated-test fixture.

Preparation also rejects digest mismatches, oversized/unsafe XML, duplicate page
identities, reserved cell/page collisions, repeated preparation and pre-existing
markers. It does not modify existing labels to force a compatibility pass.

## Compatibility and rendering

For a prepared base, pass the loaded external profile, `RenderCapability.LABEL_ONLY`,
and a `ScopeSelection` with one explicit synthetic context to `inspect_base`.
Bind that context's `partition_views` entry to **CCPM Test Controls**. Use the
returned compatibility result and the exact prepared-byte hash with
`render_label_only`; recorded timestamp, projection, profile and input identities
must remain pinned for deterministic results. The synthetic tests provide a
complete executable example:
[test_ccpm_test_profile.py](../../../tests/unit/topology/test_ccpm_test_profile.py).

An unprepared source is deliberately incompatible. The profile is not published
in the package, so merely choosing its ID in the current web form will not work.
Web registration, explicit base approval, multi-context mappings and official
publication remain separate implementation decisions, not part of this test.

## Verification and remaining decisions

Tests generate synthetic two-page diagrams and confirmed synthetic CTL-002
answers; they never open the user-supplied files. Coverage includes component
tampering, deterministic output, exact changed-cell inventory, preservation,
missing/duplicate markers, unknown markers, invalid hashes, source overwrites,
workspace escapes and Windows final-path restrictions.

To bind existing application pages instead of this test-only page, an architect
must approve exact target cells, allowed replacements, page/context semantics
and protected/generated regions. Workbook-to-resource and interface-to-edge
mappings remain unapproved. This profile does not close C00-C10 or certify the
supplied diagram, its underlying facts, Oracle or release readiness.
